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


def _llm_unavailable_reason(config) -> str | None:
    """Las pruebas `llm_real` gastan cuota del proveedor. Solo corren si se piden con
    `-m llm_real` y `.env` tiene LLM_CLIENT=real y clave."""
    if "llm_real" not in (config.getoption("-m") or ""):
        return "Prueba con el modelo real. Ejecútela con: pytest -m llm_real"
    try:
        settings = get_settings()
    except ValidationError:
        return "Configuración inválida en .env"
    if settings.llm_client != "real" or not settings.llm_api_key.get_secret_value():
        return "Requiere LLM_CLIENT=real y LLM_API_KEY en .env"
    return None


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "db" in item.keywords:
            reason = _db_unavailable_reason()
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))
        if "llm_real" in item.keywords:
            reason = _llm_unavailable_reason(config)
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))
