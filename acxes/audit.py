"""Auditoría de decisiones y respuestas.

La auditoría es una salida separada del flujo de datos: nunca se envía al LLM ni al
cliente. Los sinks pueden ser una tabla append-only o un doble de pruebas.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from json import dumps
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg

from acxes.config import Settings, postgres_dsn


@dataclass(frozen=True)
class AuditEvent:
    user_id: UUID | None
    query: str | None
    decision: Mapping[str, Any]
    policy_version: str | None
    chunk_ids: tuple[str, ...] = ()
    response: str | None = None
    tool_calls: Sequence[Mapping[str, Any]] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)
    trace_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditSink(Protocol):
    def write(self, event: AuditEvent) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class PostgresAuditSink:
    """Escribe con el rol de aplicación, que solo tiene INSERT en audit_log."""

    def __init__(self, settings: Settings) -> None:
        self._dsn = postgres_dsn(settings, role="app")

    def write(self, event: AuditEvent) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log
                    (trace_id, occurred_at, user_id, query, tool_calls, decision,
                     policy_version, chunk_ids, response, detail)
                VALUES
                    (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb)
                """,
                (
                    event.trace_id,
                    event.occurred_at,
                    event.user_id,
                    event.query,
                    dumps(list(event.tool_calls), ensure_ascii=False),
                    dumps(dict(event.decision), ensure_ascii=False),
                    event.policy_version,
                    list(event.chunk_ids) or None,
                    event.response,
                    dumps(dict(event.detail), ensure_ascii=False),
                ),
            )


def audit_event(
    sink: AuditSink | None,
    *,
    user_id: UUID | None,
    query: str | None,
    decision: Mapping[str, Any],
    policy_version: str | None,
    chunk_ids: tuple[str, ...] = (),
    response: str | None = None,
    tool_calls: Sequence[Mapping[str, Any]] = (),
    detail: Mapping[str, Any] | None = None,
) -> None:
    if sink is not None:
        sink.write(
            AuditEvent(
                user_id=user_id,
                query=query,
                decision=decision,
                policy_version=policy_version,
                chunk_ids=chunk_ids,
                response=response,
                tool_calls=tool_calls,
                detail=detail or {},
            )
        )
