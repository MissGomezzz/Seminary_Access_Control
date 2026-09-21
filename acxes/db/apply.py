"""Aplica el esquema compartido, los roles, los privilegios, RLS y el seed.

Uso:
    python -m acxes.db.apply

Se conecta con el rol propietario. Es idempotente: recrea las tablas y los datos
provisionales. Funciona igual en Windows, en Docker y en CI, sin necesitar `psql`.
"""

from pathlib import Path

import psycopg
from psycopg import sql

from acxes.config import Settings, get_settings, postgres_dsn

_SQL_DIR = Path(__file__).parent


def _run_file(conn: psycopg.Connection, name: str) -> None:
    conn.execute((_SQL_DIR / name).read_text(encoding="utf-8"))


def _ensure_roles(conn: psycopg.Connection, settings: Settings) -> None:
    """Crea o actualiza los roles de aplicación y de auditoría. Ninguno es superusuario
    ni tiene BYPASSRLS. Se exige contraseña para no dejar roles con clave vacía."""
    roles = (
        ("acxes_app", settings.postgres_app_password),
        ("acxes_audit", settings.postgres_audit_password),
    )
    for name, password in roles:
        secret = password.get_secret_value()
        if not secret:
            raise SystemExit(
                f"Falta la contraseña del rol {name}. Defínala en .env "
                "(POSTGRES_APP_PASSWORD y POSTGRES_AUDIT_PASSWORD)."
            )
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            sql.SQL(
                "{} ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}"
            ).format(sql.SQL(verb), sql.Identifier(name), sql.Literal(secret))
        )


def apply(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with psycopg.connect(postgres_dsn(settings), autocommit=True) as conn:
        _run_file(conn, "schema.sql")
        _ensure_roles(conn, settings)
        _run_file(conn, "grants.sql")
        _run_file(conn, "rls.sql")
        _run_file(conn, "seed.sql")


if __name__ == "__main__":
    apply()
    print("Esquema, roles, RLS y datos provisionales aplicados.")
