"""Atributos de autorización del sujeto, leídos de la base en cada evaluación del PDP.

La base es la fuente de verdad para autorizar. Del token solo se usa `sub` para identificar
al usuario, de modo que una revocación de rol, dependencia o etiqueta surte efecto en la
siguiente evaluación sin esperar a que expire el token (ARQUITECTURA.md 5.5).

La conexión usa el rol `acxes_pdp`, que solo puede ejecutar la función `pdp_subject`
(acxes/db/pdp.sql) y no lee ninguna tabla directamente.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import psycopg

from acxes.config import Settings, postgres_dsn


@dataclass(frozen=True)
class SubjectRecord:
    roles: tuple[str, ...]
    dept: str
    acl_tags: tuple[str, ...]


class SubjectStore(Protocol):
    def lookup(self, user_id: UUID) -> SubjectRecord | None:
        """Devuelve los atributos del usuario, o None si no existe. Ante un fallo lanza."""
        ...


class PostgresSubjectStore:
    def __init__(
        self,
        settings: Settings,
        timeout_ms: int = 500,
        connect: Callable[..., psycopg.Connection] = psycopg.connect,
    ) -> None:
        self._dsn = postgres_dsn(settings, role="pdp")
        self._timeout_ms = timeout_ms
        self._connect = connect

    def lookup(self, user_id: UUID) -> SubjectRecord | None:
        # P14: la consulta no puede superar el tiempo máximo del PDP
        with (
            self._connect(self._dsn, connect_timeout=2) as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            cur.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(self._timeout_ms),)
            )
            cur.execute("SELECT roles, dept, acl_tags FROM pdp_subject(%s)", (user_id,))
            row = cur.fetchone()
        if row is None:
            return None
        roles, dept, acl_tags = row
        return SubjectRecord(tuple(roles), dept, tuple(acl_tags))
