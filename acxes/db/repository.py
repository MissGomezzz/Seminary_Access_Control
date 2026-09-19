"""Acceso a los datos institucionales.

Deliberadamente NO expone ningún filtro por rol o dependencia: esa es la
característica que define a la arquitectura Unsecure (B1). El filtro por rol
llega en una etapa posterior del seminario, con el PDP (`acxes/pdp/`) y RLS
(ver `docs/ARQUITECTURA.md`).
"""

from dataclasses import dataclass
from typing import Protocol

import psycopg

from acxes.config import Settings, postgres_dsn


@dataclass(frozen=True)
class Employee:
    id: int
    full_name: str
    role: str
    team_id: int | None
    salary: float


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    manager_id: int | None


class InstitutionalRepository(Protocol):
    """Contrato mínimo. Nótese la ausencia de cualquier parámetro de identidad
    o de rol en las firmas: en B1 no existe ese concepto en esta capa."""

    def find_employee_by_name(self, full_name: str) -> Employee | None: ...
    def list_team_members(self, team_id: int) -> list[Employee]: ...
    def payroll_report(self) -> list[Employee]: ...
    def team_led_by(self, manager_full_name: str) -> Team | None: ...


class PostgresInstitutionalRepository:
    """Implementación real, sin ninguna cláusula WHERE de autorización."""

    def __init__(self, settings: Settings) -> None:
        self._dsn = postgres_dsn(settings)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn)

    def find_employee_by_name(self, full_name: str) -> Employee | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, full_name, role, team_id, salary "
                "FROM employees WHERE full_name ILIKE %s",
                (f"%{full_name}%",),
            )
            row = cur.fetchone()
            return Employee(*row) if row else None

    def list_team_members(self, team_id: int) -> list[Employee]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, full_name, role, team_id, salary "
                "FROM employees WHERE team_id = %s",
                (team_id,),
            )
            return [Employee(*row) for row in cur.fetchall()]

    def payroll_report(self) -> list[Employee]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, full_name, role, team_id, salary FROM employees")
            return [Employee(*row) for row in cur.fetchall()]

    def team_led_by(self, manager_full_name: str) -> Team | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT t.id, t.name, t.manager_id FROM teams t "
                "JOIN employees e ON e.id = t.manager_id "
                "WHERE e.full_name ILIKE %s",
                (f"%{manager_full_name}%",),
            )
            row = cur.fetchone()
            return Team(*row) if row else None
