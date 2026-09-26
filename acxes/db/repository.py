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
from acxes.retrieval.lexical import SEARCH_CHUNKS_SQL, keywords_to_or_query


@dataclass(frozen=True)
class UserProfile:
    id: str
    full_name: str
    role: str
    dept: str
    clearance: str
    acl_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: str
    doc_id: str
    title: str
    content: str


@dataclass(frozen=True)
class DocumentRecord:
    doc_id: str
    title: str
    chunks: tuple[ChunkHit, ...]


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

    def __init__(self, settings: Settings) -> None:
        self._dsn = postgres_dsn(settings, role="owner")

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
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(SEARCH_CHUNKS_SQL, {"q": keywords_to_or_query(keywords), "k": k})
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
