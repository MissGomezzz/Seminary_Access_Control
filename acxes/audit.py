"""Auditoría de eventos de acceso sin exponer secretos ni contenido de documentos."""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from acxes.config import Settings, postgres_dsn

log = logging.getLogger("acxes.audit")


class AuditError(Exception):
    """La auditoría obligatoria no pudo persistirse."""


class AuditLogger(Protocol):
    def record(self, event: dict[str, Any]) -> None: ...


class NullAuditLogger:
    """Doble explícito para demo y pruebas que no requieren PostgreSQL."""

    def record(self, _event: dict[str, Any]) -> None:
        return None


class PostgresAuditLogger:
    """Escribe únicamente con `acxes_audit`; nunca registra el texto recuperado."""

    def __init__(self, settings: Settings) -> None:
        self._dsn = postgres_dsn(settings, role="audit")

    def record(self, event: dict[str, Any]) -> None:
        try:
            with psycopg.connect(self._dsn, connect_timeout=3) as conn, conn.transaction():
                conn.execute(
                    """
                    INSERT INTO audit_log
                        (trace_id, user_id, query, tool_calls, decision, policy_version,
                         chunk_ids, response, detail)
                    VALUES (%(trace_id)s, %(user_id)s, %(query)s, %(tool_calls)s::jsonb,
                            %(decision)s::jsonb, %(policy_version)s, %(chunk_ids)s,
                            %(response)s, %(detail)s::jsonb)
                    """,
                    {
                        "trace_id": event["trace_id"],
                        "user_id": event.get("user_id"),
                        "query": event.get("query"),
                        "tool_calls": Jsonb(event.get("tool_calls", {})),
                        "decision": Jsonb(event.get("decision", {})),
                        "policy_version": event.get("policy_version"),
                        "chunk_ids": event.get("chunk_ids", []),
                        "response": event.get("response"),
                        "detail": Jsonb(event.get("detail", {})),
                    },
                )
        except psycopg.Error as exc:
            log.error("no se pudo persistir la auditoría (%s)", type(exc).__name__)
            raise AuditError from exc


def audit_event(
    trace_id: UUID,
    user_id: UUID,
    query: str,
    decision: dict[str, Any],
    policy_version: str,
    chunk_ids: tuple[str, ...],
    response: str,
    *,
    tool_calls: int,
    redactions: int,
    invalid_citations: int,
) -> dict[str, Any]:
    """Construye un evento acotado; no incluye JWT, claims ni contenido de chunks."""
    return {
        "trace_id": trace_id,
        "user_id": user_id,
        "query": query[:2000],
        "tool_calls": {"count": tool_calls},
        "decision": decision,
        "policy_version": policy_version,
        "chunk_ids": list(chunk_ids),
        "response": response[:10000],
        "detail": {"redactions": redactions, "invalid_citations": invalid_citations},
    }
