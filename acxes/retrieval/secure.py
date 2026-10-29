"""Servicio de recuperación de S (etapa 3).

Es el único componente de S con credencial de base de datos, y usa el rol de aplicación
`acxes_app`, sin superusuario ni BYPASSRLS. Recibe el SecurityContext y la decisión del PDP,
nunca parámetros de identidad sueltos. En cada transacción fija las variables de sesión de
docs/VARIABLES_SESION.md a partir del predicado y además aplica el mismo predicado en el
`WHERE`, de modo que el filtro va antes de la recuperación y RLS queda como segunda red.

Si la decisión no es de acceso, no abre conexión ni calcula el vector de la consulta. Un
documento inexistente y uno no autorizado producen el mismo resultado (P12).

En modo híbrido el vector de la consulta se calcula aquí, en el proceso del servicio, con el
modelo local. Nunca sale del servicio: no va al gateway, al modelo de lenguaje ni a la auditoría.
"""

from collections.abc import Callable, Sequence
from decimal import Decimal
from uuid import UUID

import psycopg

from acxes.config import Settings, postgres_dsn
from acxes.dev_audit import dev_audit
from acxes.pdp.model import Decision, Predicate
from acxes.retrieval.embedding import Embedder, build_embedder, to_pgvector
from acxes.retrieval.lexical import (
    SECURE_HYBRID_SEARCH_CHUNKS_SQL,
    SECURE_SEARCH_CHUNKS_SQL,
    keywords_to_or_query,
    keywords_to_text,
    predicate_clause,
)
from acxes.retrieval.types import ChunkHit, ChunkMeta, DocumentRecord
from acxes.security_context import SecurityContext

_DOCUMENT_SQL = (
    f"SELECT d.title FROM documents d WHERE d.id = %(doc_id)s AND {predicate_clause('d')}"
)
_DOCUMENT_CHUNKS_SQL = (
    f"SELECT c.id, c.content FROM chunks c WHERE c.doc_id = %(doc_id)s AND {predicate_clause('c')} "
    "ORDER BY c.chunk_index"
)
_DESCRIBE_SQL = f"""
SELECT c.id, c.doc_id, d.title, c.dept, c.sensitivity::text, c.acl_tags
FROM chunks c
JOIN documents d ON d.id = c.doc_id
WHERE c.id = ANY(%(chunk_ids)s::uuid[]) AND {predicate_clause("c")}
"""
# Solo los salarios de las nóminas que el usuario podría leer: mismo predicado que la búsqueda
# y RLS sobre payroll como segunda red. El filtro opcional es la dependencia del empleado
_SALARY_SQL = f"""
SELECT p.salary
FROM payroll p
WHERE {predicate_clause("p")}
  AND (%(dept)s::text IS NULL OR p.employee_dept = %(dept)s::text)
"""


class RetrievalDenied(Exception):
    """La decisión del PDP no permite recuperar. No se tocó la base."""


class RetrievalError(Exception):
    """Fallo de la base. El mensaje es genérico y el detalle no sale del servicio."""


class SecureRetrievalService:
    def __init__(
        self,
        settings: Settings,
        connect: Callable[[str], psycopg.Connection] = psycopg.connect,
        embedder: Embedder | None = None,
    ) -> None:
        self._dsn = postgres_dsn(settings, role="app")
        self._k = settings.retrieval_k
        self._connect = connect
        self._hybrid = settings.retrieval_mode == "hybrid"
        self._embedder = (embedder or build_embedder(settings)) if self._hybrid else None
        self._hybrid_params = {
            "n": settings.retrieval_candidates,
            "rrf_k": settings.rrf_k,
            "min_sim": settings.embedding_min_similarity,
        }

    def search(
        self, ctx: SecurityContext, decision: Decision, keywords: list[str]
    ) -> list[ChunkHit]:
        predicate = _require_allowed(ctx, decision)
        params = _predicate_params(predicate) | {"q": keywords_to_or_query(keywords), "k": self._k}
        sql = SECURE_SEARCH_CHUNKS_SQL
        if self._hybrid:
            # Después de la autorización y antes de abrir la conexión
            params |= self._hybrid_params | {"qv": self._query_vector(keywords)}
            sql = SECURE_HYBRID_SEARCH_CHUNKS_SQL
        dev_audit(
            "retrieval: search modo=%s q=%r depts=%s max=%s tags=%s k=%s",
            "hybrid" if self._hybrid else "lexical",
            params["q"], params["depts"], params["max_sensitivity"], params["acl_tags"], self._k,
        )
        rows = self._run(decision, lambda cur: _fetch(cur, sql, params))
        dev_audit("retrieval: search filas=%d", len(rows))
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

    def describe_chunks(
        self, ctx: SecurityContext, decision: Decision, chunk_ids: Sequence[str]
    ) -> list[ChunkMeta]:
        """Metadatos de los fragmentos que vio el modelo, para citar sus fuentes en la interfaz.

        Aplica el mismo predicado y las mismas variables de sesión que la búsqueda, así que un
        identificador no autorizado no devuelve nada, igual que uno inexistente (P12). Conserva
        el orden recibido y no devuelve contenido.
        """
        predicate = _require_allowed(ctx, decision)
        if not chunk_ids:
            return []
        params = _predicate_params(predicate) | {"chunk_ids": list(chunk_ids)}
        rows = self._run(decision, lambda cur: _fetch(cur, _DESCRIBE_SQL, params))
        dev_audit("retrieval: describe_chunks pedidos=%d encontrados=%d", len(chunk_ids), len(rows))
        found = {
            str(cid): ChunkMeta(str(cid), str(did), title, dept, sens, tuple(tags))
            for cid, did, title, dept, sens, tags in rows
        }
        return [found[c] for c in chunk_ids if c in found]

    def aggregate_salary(
        self,
        ctx: SecurityContext,
        decision: Decision,
        dept: str | None = None,
    ) -> list[Decimal]:
        """Salarios de las nóminas visibles para el usuario. La cohorte la fija el predicado y
        nunca el modelo. `dept` solo puede acotarla, nunca ampliarla."""
        predicate = _require_allowed(ctx, decision)
        params = _predicate_params(predicate) | {"dept": dept}
        rows = self._run(decision, lambda cur: _fetch(cur, _SALARY_SQL, params))
        return [Decimal(str(row[0])) for row in rows]

    def _query_vector(self, keywords: list[str]) -> str:
        """Vector de la consulta como literal de pgvector. Un fallo del modelo es un error de
        recuperación genérico: no se vuelve en silencio a la búsqueda léxica."""
        assert self._embedder is not None
        try:
            return to_pgvector(self._embedder.embed_query(keywords_to_text(keywords)))
        except Exception as exc:  # noqa: BLE001 - el detalle no sale del servicio
            dev_audit("retrieval: error del modelo de embeddings %s: %s", type(exc).__name__, exc)
            raise RetrievalError("error de recuperación") from exc

    def _run(self, decision: Decision, query):
        variables = _session_variables(decision)
        try:
            with self._connect(self._dsn) as conn, conn.transaction(), conn.cursor() as cur:
                for name, value in variables.items():
                    # Equivale a SET LOCAL, pero admite parámetros ligados
                    cur.execute("SELECT set_config(%s, %s, true)", (name, value))
                return query(cur)
        except psycopg.Error as exc:
            dev_audit("retrieval: error de base %s: %s", type(exc).__name__, exc)
            raise RetrievalError("error de recuperación") from exc


def _require_allowed(ctx: SecurityContext, decision: Decision) -> Predicate:
    if not decision.allowed:
        raise RetrievalDenied("decisión de denegación")
    assert decision.predicate is not None
    # La decisión debe corresponder a este contexto
    if decision.predicate.owner_id != ctx.user_id or decision.policy_version != ctx.policy_version:
        dev_audit(
            "retrieval: decisión no corresponde al contexto (owner=%s user=%s pv=%s/%s)",
            decision.predicate.owner_id, ctx.user_id, decision.policy_version, ctx.policy_version,
        )
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
