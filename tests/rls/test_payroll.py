"""Salarios de nómina bajo RLS, directo contra la base y a través del servicio de recuperación.

`payroll` es un índice de las nóminas individuales, como `chunks`: la ingesta extrae el salario
del cuerpo de cada nómina y la tabla hereda la clasificación del documento. Lo esperado sale
del oráculo y de los hints del plan, nunca de la base. Requieren `python -m acxes.db.apply`.
"""

from decimal import Decimal

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.ingestion.corpus_plan import doc_uuid, load_plan, parse_salaries
from acxes.retrieval.secure import SecureRetrievalService
from tests.rls.contexts import database_pdp, security_context
from tests.rls.oracle import PERSONAS, visible
from tests.rls.test_rls import CONTEXTOS, DIEGO, SOFIA

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def nominas() -> dict:
    """Slug de cada nómina individual con su especificación."""
    return {s.slug: s for s in load_plan() if s.doc_type == "nomina"}


@pytest.fixture(scope="module")
def slug_by_id(nominas) -> dict:
    return {doc_uuid(slug): slug for slug in nominas}


@pytest.fixture
def app_conn():
    with psycopg.connect(postgres_dsn(get_settings(), role="app"), autocommit=True) as conn:
        yield conn


@pytest.fixture
def owner_conn():
    with psycopg.connect(postgres_dsn(get_settings()), autocommit=True) as conn:
        yield conn


def _payroll(conn: psycopg.Connection, ctx: dict) -> list[tuple]:
    with conn.transaction():
        for name, value in ctx.items():
            conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        return conn.execute("SELECT doc_id, salary FROM payroll").fetchall()


def _planned(spec) -> Decimal:
    (salary,) = parse_salaries(spec.hint)
    return salary


def test_hay_un_salario_por_nomina_y_es_el_del_plan(owner_conn, nominas, slug_by_id):
    filas = owner_conn.execute("SELECT doc_id, salary FROM payroll").fetchall()

    assert {slug_by_id[d]: s for d, s in filas} == {
        slug: _planned(spec) for slug, spec in nominas.items()
    }


def test_el_salario_hereda_la_clasificacion_de_su_nomina(owner_conn):
    distintas = owner_conn.execute(
        "SELECT count(*) FROM payroll p JOIN documents d ON d.id = p.doc_id "
        "WHERE (p.dept, p.sensitivity, p.owner_id, p.acl_tags) "
        "IS DISTINCT FROM (d.dept, d.sensitivity, d.owner_id, d.acl_tags)"
    ).fetchone()[0]
    assert distintas == 0


@pytest.mark.parametrize("nombre", list(CONTEXTOS))
def test_cada_usuario_ve_solo_los_salarios_de_las_nominas_que_puede_leer(
    app_conn, nominas, slug_by_id, nombre
):
    vistos = {slug_by_id[d] for d, _ in _payroll(app_conn, CONTEXTOS[nombre])}
    esperados = {slug for slug, spec in nominas.items() if visible(PERSONAS[nombre], spec)}

    assert vistos == esperados


def test_un_empleado_solo_ve_su_propio_salario(app_conn, slug_by_id):
    filas = _payroll(app_conn, SOFIA)
    assert [slug_by_id[d] for d, _ in filas] == ["nomina-individual-sofia-ariza"]


def test_sin_variables_de_sesion_no_hay_salarios(app_conn):
    assert _payroll(app_conn, {}) == []
    assert _payroll(app_conn, {name: "" for name in SOFIA}) == []


def test_la_politica_esta_forzada_y_el_rol_de_aplicacion_no_lee_users(owner_conn, app_conn):
    forzada = owner_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'payroll'"
    ).fetchone()
    assert forzada == (True, True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT 1 FROM users")


def test_ningun_salario_vive_fuera_de_payroll(owner_conn):
    """users ya no guarda salarios y la vista payroll_cohort, que los leía sin RLS, no existe."""
    columnas = owner_conn.execute(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'salary'"
    ).fetchall()
    assert columnas == [("payroll",)]
    assert owner_conn.execute("SELECT to_regclass('payroll_cohort')").fetchone()[0] is None


def test_un_cambio_de_clasificacion_llega_al_salario(owner_conn, app_conn):
    """Si la nómina de Laura pasara a ser de Sofía, Sofía vería ese salario. Se revierte."""
    nomina = doc_uuid("nomina-individual-laura-martinez")
    sofia = SOFIA["app.user_id"]
    with owner_conn.transaction(force_rollback=True):
        owner_conn.execute("UPDATE documents SET owner_id = %s WHERE id = %s", (sofia, nomina))
        dueno = owner_conn.execute(
            "SELECT owner_id::text FROM payroll WHERE doc_id = %s", (nomina,)
        ).fetchone()[0]
    assert dueno == sofia


def test_una_nomina_no_puede_bajar_de_confidencial(owner_conn):
    nomina = doc_uuid("nomina-individual-sofia-ariza")
    with pytest.raises(psycopg.errors.CheckViolation), owner_conn.transaction():
        owner_conn.execute("UPDATE documents SET sensitivity = 'interno' WHERE id = %s", (nomina,))


@pytest.fixture(scope="module")
def pdp():
    return database_pdp()


@pytest.fixture(scope="module")
def service() -> SecureRetrievalService:
    return SecureRetrievalService(get_settings())


@pytest.mark.parametrize("nombre", list(PERSONAS))
def test_el_agregado_suma_solo_lo_que_el_usuario_puede_leer(service, pdp, nominas, nombre):
    ctx = security_context(nombre, pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    valores = service.aggregate_salary(ctx, decision, None)
    esperados = [_planned(spec) for spec in nominas.values() if visible(PERSONAS[nombre], spec)]

    assert sorted(valores) == sorted(esperados)


def test_el_filtro_por_dependencia_solo_acota_la_cohorte(service, pdp, nominas):
    ctx = security_context("Diego", pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    financiera = service.aggregate_salary(ctx, decision, "financiera")
    todos = service.aggregate_salary(ctx, decision, None)

    # Sofía, Belén y Laura son de financiera
    assert sorted(financiera) == sorted(
        _planned(nominas[f"nomina-individual-{s}"])
        for s in ("sofia-ariza", "belen-quintero", "laura-martinez")
    )
    assert len(todos) == len(nominas)
    # Un supervisor de académica no amplía su cohorte pidiendo otra dependencia
    ctx = security_context("Carlos", pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    assert service.aggregate_salary(ctx, decision, "financiera") == []


def test_el_contexto_del_administrador_no_concede_salarios_por_rol(app_conn):
    """RLS no tiene excepción por rol: con el tope en interno, el administrador no ve nóminas
    ajenas aunque app.roles diga administrador."""
    ctx = dict(DIEGO, **{"app.clearance": "interno"})
    vistas = {doc_id for doc_id, _ in _payroll(app_conn, ctx)}
    assert vistas == {doc_uuid("nomina-individual-diego-fajardo")}
