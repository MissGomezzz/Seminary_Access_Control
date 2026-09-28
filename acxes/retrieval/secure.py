"""Servicio de recuperación de S (etapa 3).

Es el único componente de S con credencial de base de datos, y usa el rol de aplicación
`acxes_app`, sin superusuario ni BYPASSRLS. Recibe el SecurityContext y la decisión del PDP,
nunca parámetros de identidad sueltos. En cada transacción fija las variables de sesión de
docs/VARIABLES_SESION.md a partir del predicado y además aplica el mismo predicado en el
`WHERE`, de modo que el filtro va antes de la recuperación y RLS queda como segunda red.

Si la decisión no es de acceso, no abre conexión. Un documento inexistente y uno no
autorizado producen el mismo resultado (P12).
"""

from collections.abc import Callable
from uuid import UUID

import psycopg

from acxes.config import Settings, postgres_dsn
from acxes.pdp.model import Decision, Predicate
from acxes.retrieval.lexical import SECURE_SEARCH_CHUNKS_SQL, keywords_to_or_query, predicate_clause
from acxes.retrieval.types import ChunkHit, DocumentRecord
from acxes.security_context import SecurityContext

_DOCUMENT_SQL = (
    f"SELECT d.title FROM documents d WHERE d.id = %(doc_id)s AND {predicate_clause('d')}"
)
_DOCUMENT_CHUNKS_SQL = (
    f"SELECT c.id, c.content FROM chunks c WHERE c.doc_id = %(doc_id)s AND {predicate_clause('c')} "
    "ORDER BY c.chunk_index"
)


class RetrievalDenied(Exception):
    """La decisión del PDP no permite recuperar. No se tocó la base."""


class RetrievalError(Exception):
    """Fallo de la base. El mensaje es genérico y el detalle no sale del servicio."""


class SecureRetrievalService:
    def __init__(
        self,
        settings: Settings,
        connect: Callable[[str], psycopg.Connection] = psycopg.connect,
    ) -> None:
        self._dsn = postgres_dsn(settings, role="app")
        self._k = settings.retrieval_k
        self._connect = connect

    def search(
        self, ctx: SecurityContext, decision: Decision, keywords: list[str]
    ) -> list[ChunkHit]:
        predicate = _require_allowed(ctx, decision)
        params = _predicate_params(predicate) | {"q": keywords_to_or_query(keywords), "k": self._k}
        rows = self._run(decision, lambda cur: _fetch(cur, SECURE_SEARCH_CHUNKS_SQL, params))
        return [ChunkHit(str(cid), str(did), title, content) for cid, did, title, content in rows]

    def read_document(
        self, ctx: SecurityContext, decision: Decision, doc_id: UUID
    ) -> DocumentRecord | None:
        predicate = _require_allowed(ctx, decision)
        params = _predicate_params(predicate) | {"doc_id": doc_id}

        def query(cur: psycopg.Cursor) -> DocumentRecord | None:
            row = _fetch(cur, _DOCUMENT_SQL, params)
            if not row:
                return None
            title = row[0][0]
            chunks = tuple(
                ChunkHit(str(cid), str(doc_id), title, content)
                for cid, content in _fetch(cur, _DOCUMENT_CHUNKS_SQL, params)
            )
            return DocumentRecord(str(doc_id), title, chunks)

        return self._run(decision, query)

    def _run(self, decision: Decision, query):
        variables = _session_variables(decision)
        try:
            with self._connect(self._dsn) as conn, conn.transaction(), conn.cursor() as cur:
                for name, value in variables.items():
                    # Equivale a SET LOCAL, pero admite parámetros ligados
                    cur.execute("SELECT set_config(%s, %s, true)", (name, value))
                return query(cur)
        except psycopg.Error as exc:
            raise RetrievalError("error de recuperación") from exc


def _require_allowed(ctx: SecurityContext, decision: Decision) -> Predicate:
    if not decision.allowed:
        raise RetrievalDenied("decisión de denegación")
    assert decision.predicate is not None
    # La decisión debe corresponder a este contexto
    if decision.predicate.owner_id != ctx.user_id or decision.policy_version != ctx.policy_version:
        raise RetrievalDenied("la decisión no corresponde al contexto")
    return decision.predicate


def _predicate_params(p: Predicate) -> dict:
    return {
        "depts": list(p.allowed_depts),
        "max_sensitivity": p.max_sensitivity.name,
        "owner_id": p.owner_id,
        "acl_tags": list(p.acl_tags),
    }


def _session_variables(decision: Decision) -> dict[str, str]:
    """Variables de docs/VARIABLES_SESION.md. Las listas van separadas por comas."""
    p = decision.predicate
    assert p is not None
    return {
        "app.user_id": str(p.owner_id),
        "app.roles": decision.role or "",
        "app.dept": decision.dept or "",
        "app.allowed_depts": ",".join(p.allowed_depts),
        "app.clearance": p.max_sensitivity.name,
        "app.acl_tags": ",".join(p.acl_tags),
    }


def _fetch(cur: psycopg.Cursor, sql: str, params: dict) -> list[tuple]:
    cur.execute(sql, params)
    return cur.fetchall()
