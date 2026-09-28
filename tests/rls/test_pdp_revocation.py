"""Revocación inmediata (ARQUITECTURA.md 5.5): la base es la fuente de verdad para autorizar.

Cada prueba cambia la base con el propietario, confirma el cambio para que el PDP lo vea desde
su propia conexión, y restaura el valor original al terminar. El SecurityContext es siempre el
mismo, como si el token no hubiera cambiado.
"""

from contextlib import contextmanager
from uuid import UUID

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.ingestion.corpus_plan import doc_uuid
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.pdp.model import Sensitivity
from acxes.pdp.subject_store import PostgresSubjectStore
from acxes.retrieval.secure import SecureRetrievalService
from tests.rls.contexts import database_pdp, security_context

pytestmark = pytest.mark.db

ACTA_COMITE = doc_uuid("acta-del-comite-disciplinario-2026-01")


@pytest.fixture(scope="module")
def pdp():
    return database_pdp()


@pytest.fixture(scope="module")
def service():
    return SecureRetrievalService(get_settings())


@contextmanager
def _cambio_en_la_base(sql: str, restore: str, user_id: UUID):
    dsn = postgres_dsn(get_settings())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql, (user_id,))
        try:
            yield
        finally:
            conn.execute(restore, (user_id,))


def test_revocar_una_etiqueta_surte_efecto_con_el_mismo_token(pdp, service):
    ctx = security_context("Carlos", pdp)
    antes = pdp.evaluate(ctx, "read", "documentos")
    assert service.read_document(ctx, antes, ACTA_COMITE) is not None

    with _cambio_en_la_base(
        "UPDATE users SET acl_tags = '{}' WHERE id = %s",
        "UPDATE users SET acl_tags = '{comite_disciplinario}' WHERE id = %s",
        ctx.user_id,
    ):
        despues = pdp.evaluate(ctx, "read", "documentos")
        assert despues.predicate.acl_tags == ()
        assert "acl_tags" in despues.claims_drift
        assert service.read_document(ctx, despues, ACTA_COMITE) is None

    assert service.read_document(ctx, pdp.evaluate(ctx, "read", "documentos"), ACTA_COMITE)


def test_degradar_el_rol_surte_efecto_con_el_mismo_token(pdp, service):
    ctx = security_context("Laura", pdp)
    presupuesto = doc_uuid("presupuesto-detallado-centro-de-costo-infraestructura")

    with _cambio_en_la_base(
        "UPDATE user_roles SET role_id = (SELECT id FROM roles WHERE name = 'empleado') "
        "WHERE user_id = %s",
        "UPDATE user_roles SET role_id = (SELECT id FROM roles WHERE name = 'supervisor') "
        "WHERE user_id = %s",
        ctx.user_id,
    ):
        decision = pdp.evaluate(ctx, "read", "documentos")
        assert decision.role == "empleado"
        assert decision.predicate.max_sensitivity == Sensitivity.interno
        assert service.read_document(ctx, decision, presupuesto) is None

    decision = pdp.evaluate(ctx, "read", "documentos")
    assert service.read_document(ctx, decision, presupuesto) is not None


def test_cambiar_la_dependencia_surte_efecto_con_el_mismo_token(pdp):
    ctx = security_context("Sofía", pdp)

    with _cambio_en_la_base(
        "UPDATE users SET dept = 'academica' WHERE id = %s",
        "UPDATE users SET dept = 'financiera' WHERE id = %s",
        ctx.user_id,
    ):
        decision = pdp.evaluate(ctx, "search", "documentos")
        assert set(decision.predicate.allowed_depts) == {"institucional", "academica"}
        assert decision.dept == "academica"


def test_quitar_el_rol_deniega_con_el_mismo_token(pdp):
    ctx = security_context("Sofía", pdp)
    dsn = postgres_dsn(get_settings())
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM user_roles WHERE user_id = %s", (ctx.user_id,))
        try:
            assert pdp.evaluate(ctx, "search", "documentos").reason == "roles"
        finally:
            conn.execute(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT %s, id FROM roles WHERE name = 'empleado'",
                (ctx.user_id,),
            )
    assert pdp.evaluate(ctx, "search", "documentos").allowed


def test_el_almacen_devuelve_los_atributos_de_la_base():
    store = PostgresSubjectStore(get_settings())
    carlos = store.lookup(UUID("00000000-0000-4000-a000-000000000005"))
    assert carlos is not None
    assert carlos.roles == ("supervisor",)
    assert carlos.dept == "academica"
    assert carlos.acl_tags == ("comite_disciplinario",)
    assert store.lookup(UUID("00000000-0000-4000-a000-000000000099")) is None


def test_si_la_base_no_responde_el_pdp_deniega(pdp):
    settings = get_settings().model_copy(update={"postgres_port": 1})
    roto = PolicyDecisionPoint(PostgresSubjectStore(settings))
    ctx = security_context("Diego", pdp)
    decision = roto.evaluate(ctx, "search", "documentos")

    assert decision.decision == "deny"
    assert decision.reason in {"subject_error", "timeout"}


@pytest.fixture
def pdp_conn():
    with psycopg.connect(postgres_dsn(get_settings(), role="pdp"), autocommit=True) as conn:
        yield conn


def test_el_rol_del_pdp_no_es_superusuario_ni_ignora_rls(pdp_conn):
    fila = pdp_conn.execute(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert fila == (False, False)


@pytest.mark.parametrize(
    "tabla", ["users", "user_roles", "roles", "documents", "chunks", "audit_log"]
)
def test_el_rol_del_pdp_no_lee_tablas(pdp_conn, tabla):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pdp_conn.execute(f"SELECT * FROM {tabla}")


def test_el_rol_de_aplicacion_no_ejecuta_la_funcion_del_pdp():
    with (
        psycopg.connect(postgres_dsn(get_settings(), role="app"), autocommit=True) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT * FROM pdp_subject(%s)", (UUID(int=0),))
