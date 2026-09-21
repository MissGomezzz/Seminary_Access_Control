import psycopg
import pytest
from pydantic import ValidationError

from acxes.config import get_settings, postgres_dsn

_db_reason: str | None = None
_db_checked = False


def _db_unavailable_reason() -> str | None:
    """Devuelve el motivo por el que las pruebas `db` no pueden correr, o None si pueden."""
    global _db_checked, _db_reason
    if _db_checked:
        return _db_reason
    _db_checked = True
    try:
        with psycopg.connect(postgres_dsn(get_settings()), connect_timeout=3) as conn:
            total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        if total == 0:
            _db_reason = "La base no tiene datos. Ejecute: python -m acxes.db.apply"
    except (psycopg.Error, OSError, ValidationError):
        _db_reason = (
            "PostgreSQL no disponible o sin esquema. Levante la base y ejecute: "
            "python -m acxes.db.apply"
        )
    return _db_reason


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "db" in item.keywords:
            reason = _db_unavailable_reason()
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))
