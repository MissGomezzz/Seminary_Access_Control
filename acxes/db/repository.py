"""Acceso a los datos institucionales para la línea base B1 (Unsecure).

Deliberadamente NO aplica ningún filtro por rol, dependencia, nivel ni etiquetas, y se
conecta con el rol propietario, una credencial amplia que ignora RLS. Esa es la
característica que define a B1. S usa el rol de aplicación, el predicado del PDP y RLS
(ver `docs/ARQUITECTURA.md`). Este módulo no debe importarse desde S.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import psycopg

from acxes.config import Settings, postgres_dsn
from acxes.retrieval.embedding import Embedder, build_embedder, to_pgvector
from acxes.retrieval.lexical import (
    HYBRID_SEARCH_CHUNKS_SQL,
    SEARCH_CHUNKS_SQL,
    keywords_to_or_query,
    keywords_to_text,
)
from acxes.retrieval.types import ChunkHit, DocumentRecord

__all__ = [
    "ChunkHit",
    "DocumentRecord",
    "InstitutionalRepository",
    "PostgresInstitutionalRepository",
    "UserProfile",
]


@dataclass(frozen=True)
class UserProfile:
    id: str
    full_name: str
    role: str
    dept: str
    clearance: str
    acl_tags: tuple[str, ...] = ()


class InstitutionalRepository(Protocol):
    """Contrato de B1. Nótese la ausencia de cualquier parámetro de identidad."""

    def list_users(self) -> list[UserProfile]: ...
    def search_chunks(self, keywords: list[str], k: int) -> list[ChunkHit]: ...
    def get_document(self, doc_id: UUID) -> DocumentRecord | None: ...


_USER_SQL = """
SELECT u.id, u.full_name, r.name, u.dept, u.clearance::text, u.acl_tags
FROM users u
JOIN user_roles ur ON ur.user_id = u.id
JOIN roles r ON r.id = ur.role_id
"""


class PostgresInstitutionalRepository:
    """Implementación real, sin ninguna cláusula WHERE de autorización."""

    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self._dsn = postgres_dsn(settings, role="owner")
        # Mismo modo, modelo y parámetros de fusión que S, para que solo cambie la autorización
        self._hybrid = settings.retrieval_mode == "hybrid"
        self._embedder = (embedder or build_embedder(settings)) if self._hybrid else None
        self._hybrid_params = {
            "n": settings.retrieval_candidates,
            "rrf_k": settings.rrf_k,
            "min_sim": settings.embedding_min_similarity,
        }

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn)

    def list_users(self) -> list[UserProfile]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(_USER_SQL + " ORDER BY u.full_name")
            return [
                UserProfile(str(uid), name, role, dept, clearance, tuple(tags))
                for uid, name, role, dept, clearance, tags in cur.fetchall()
            ]

    def search_chunks(self, keywords: list[str], k: int) -> list[ChunkHit]:
        params = {"q": keywords_to_or_query(keywords), "k": k}
        sql = SEARCH_CHUNKS_SQL
        if self._hybrid:
            assert self._embedder is not None
            vector = self._embedder.embed_query(keywords_to_text(keywords))
            params |= self._hybrid_params | {"qv": to_pgvector(vector)}
            sql = HYBRID_SEARCH_CHUNKS_SQL
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                ChunkHit(str(cid), str(did), title, content)
                for cid, did, title, content in cur.fetchall()
            ]

    def get_document(self, doc_id: UUID) -> DocumentRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT title FROM documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            if row is None:
                return None
            title = row[0]
            cur.execute(
                "SELECT id, content FROM chunks WHERE doc_id = %s ORDER BY chunk_index",
                (doc_id,),
            )
            chunks = tuple(
                ChunkHit(str(cid), str(doc_id), title, content) for cid, content in cur.fetchall()
            )
            return DocumentRecord(str(doc_id), title, chunks)
