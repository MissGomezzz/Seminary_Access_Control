"""Pruebas de RLS directas contra la base, sin pasar por la aplicación.

Se conectan como `acxes_app` y fijan las variables de sesión que el servicio de
recuperación de S fijaría a partir del predicado del PDP (docs/VARIABLES_SESION.md).
Los conjuntos esperados los calcula `oracle.py` sobre el plan del corpus a partir de
documents/MATRIZ_ACCESO.md, independiente de la política, para que un error en ella no se
copie a la prueba. Además hay aserciones explícitas por slug.
Requieren `python -m acxes.db.apply`.
"""

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.ingestion.corpus_plan import DocSpec, doc_uuid, load_plan
from tests.rls.oracle import PERSONAS, expected_slugs

pytestmark = pytest.mark.db

_USER = "00000000-0000-4000-a000-00000000000{}"


def _ctx(n: int, role: str, dept: str, depts: list[str], clearance: str, tags: list[str]) -> dict:
    return {
        "app.user_id": _USER.format(n),
        "app.roles": role,
        "app.dept": dept,
        "app.allowed_depts": ",".join(depts),
        "app.clearance": clearance,
        "app.acl_tags": ",".join(tags),
    }


SOFIA = _ctx(1, "empleado", "financiera", ["institucional", "financiera"], "interno", [])
BELEN = _ctx(2, "empleado", "financiera", ["institucional", "financiera"], "interno", [])
ANGELA = _ctx(3, "empleado", "academica", ["institucional", "academica"], "interno", [])
LAURA = _ctx(
    4,
    "supervisor",
    "financiera",
    ["institucional", "financiera"],
    "confidencial",
    ["auditoria_interna"],
)
CARLOS = _ctx(
    5,
    "supervisor",
    "academica",
    ["institucional", "academica"],
    "confidencial",
    ["comite_disciplinario"],
)
DIEGO = _ctx(
    6,
    "administrador",
    "institucional",
    ["institucional", "academica", "financiera"],
    "confidencial",
    [],
)

CONTEXTOS = {
    "Sofía": SOFIA,
    "Belén": BELEN,
    "Ángela": ANGELA,
    "Laura": LAURA,
    "Carlos": CARLOS,
    "Diego": DIEGO,
}

# Restringidos sin etiquetas: ningún usuario de prueba debe verlos
SIN_ETIQUETAS = (
    "acta-del-comite-disciplinario-sin-etiquetas-asignadas",
    "informe-de-auditoria-sin-etiquetas-asignadas",
)
ACTA_COMITE = "acta-del-comite-disciplinario-2026-01"
INFORME_AUDITORIA = "informe-de-auditoria-interna-2026-q1"


@pytest.fixture(scope="module")
def specs() -> list[DocSpec]:
    return load_plan()


@pytest.fixture(scope="module")
def slug_by_id(specs) -> dict:
    return {doc_uuid(s.slug): s.slug for s in specs}


@pytest.fixture
def app_conn():
    with psycopg.connect(postgres_dsn(get_settings(), role="app"), autocommit=True) as conn:
        yield conn


@pytest.fixture
def owner_conn():
    with psycopg.connect(postgres_dsn(get_settings()), autocommit=True) as conn:
        yield conn


def _visible(conn: psycopg.Connection, ctx: dict, table: str = "documents") -> list:
    column = "title" if table == "documents" else "content"
    with conn.transaction():
        for name, value in ctx.items():
            conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        return conn.execute(f"SELECT id, {column} FROM {table}").fetchall()


def _slugs(conn: psycopg.Connection, slug_by_id: dict, ctx: dict) -> set[str]:
    return {slug_by_id[doc_id] for doc_id, _ in _visible(conn, ctx)}


@pytest.mark.parametrize("nombre", list(CONTEXTOS))
def test_cada_usuario_ve_exactamente_lo_que_dice_la_matriz(app_conn, specs, slug_by_id, nombre):
    vistos = _slugs(app_conn, slug_by_id, CONTEXTOS[nombre])

    assert vistos == expected_slugs(PERSONAS[nombre], specs)


@pytest.mark.parametrize("nombre", list(CONTEXTOS))
def test_los_fragmentos_siguen_a_sus_documentos(app_conn, nombre):
    ctx = CONTEXTOS[nombre]
    with app_conn.transaction():
        for name, value in ctx.items():
            app_conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        doc_ids = {r[0] for r in app_conn.execute("SELECT id FROM documents").fetchall()}
        chunk_docs = {r[0] for r in app_conn.execute("SELECT doc_id FROM chunks").fetchall()}

    assert chunk_docs == doc_ids


def test_cada_empleado_ve_su_nomina_y_ninguna_ajena(app_conn, slug_by_id):
    nominas = {
        s for s in _slugs(app_conn, slug_by_id, SOFIA) if s.startswith("nomina-individual-")
    }
    assert nominas == {"nomina-individual-sofia-ariza"}


def test_las_evaluaciones_son_de_su_dueno_incluso_entre_dependencias(app_conn, slug_by_id):
    angela = _slugs(app_conn, slug_by_id, ANGELA)
    assert "evaluacion-de-desempeno-angela-gomez" in angela
    assert "evaluacion-de-desempeno-carlos-renteria" not in angela
    # Una supervisora de otra dependencia ve la propia y no la de la dependencia ajena
    laura = _slugs(app_conn, slug_by_id, LAURA)
    assert "evaluacion-de-desempeno-laura-martinez" in laura
    assert "evaluacion-de-desempeno-carlos-renteria" not in laura


def test_restringido_solo_con_la_etiqueta_de_su_area(app_conn, slug_by_id):
    laura = _slugs(app_conn, slug_by_id, LAURA)
    carlos = _slugs(app_conn, slug_by_id, CARLOS)
    assert INFORME_AUDITORIA in laura and ACTA_COMITE not in laura
    assert ACTA_COMITE in carlos and INFORME_AUDITORIA not in carlos


@pytest.mark.parametrize("nombre", list(CONTEXTOS))
def test_un_restringido_sin_etiquetas_no_lo_ve_nadie(app_conn, slug_by_id, nombre):
    assert not set(SIN_ETIQUETAS) & _slugs(app_conn, slug_by_id, CONTEXTOS[nombre])


def test_el_administrador_ve_todo_lo_confidencial_y_nada_restringido(app_conn, specs, slug_by_id):
    diego = _slugs(app_conn, slug_by_id, DIEGO)
    restringidos = {s.slug for s in specs if s.sensitivity == "restringido"}
    confidenciales = {s.slug for s in specs if s.sensitivity == "confidencial"}
    assert confidenciales <= diego
    assert not diego & restringidos


@pytest.mark.parametrize("nombre", list(CONTEXTOS))
def test_todos_ven_lo_publico_los_senuelos_y_los_documentos_con_inyeccion(
    app_conn, specs, slug_by_id, nombre
):
    generales = {s.slug for s in specs if s.kind != "normal" or s.sensitivity == "publico"}
    assert generales <= _slugs(app_conn, slug_by_id, CONTEXTOS[nombre])


def test_sin_variables_de_sesion_no_hay_filas(app_conn):
    assert _visible(app_conn, {}) == []
    assert _visible(app_conn, {}, table="chunks") == []


def test_variables_vacias_no_hay_filas(app_conn):
    ctx = {name: "" for name in SOFIA}
    assert _visible(app_conn, ctx) == []


def test_falta_el_nivel_maximo_y_no_hay_filas_por_dependencia(app_conn):
    ctx = {"app.allowed_depts": "institucional,academica,financiera"}
    assert _visible(app_conn, ctx) == []


def test_un_tope_restringido_no_concede_el_nivel_restringido(app_conn, slug_by_id):
    """Defensa en profundidad: aunque el PDP nunca lo emite, RLS no lo concede por nivel."""
    ctx = dict(DIEGO, **{"app.clearance": "restringido"})
    vistos = _slugs(app_conn, slug_by_id, ctx)

    assert ACTA_COMITE not in vistos and INFORME_AUDITORIA not in vistos
    assert not set(SIN_ETIQUETAS) & vistos


def test_restringido_solo_por_etiqueta_aunque_el_usuario_sea_administrador(app_conn, slug_by_id):
    ctx = dict(DIEGO, **{"app.acl_tags": "comite_disciplinario,auditoria_interna"})
    vistos = _slugs(app_conn, slug_by_id, ctx)

    assert ACTA_COMITE in vistos and INFORME_AUDITORIA in vistos
    assert not set(SIN_ETIQUETAS) & vistos


def test_el_orden_del_enum_es_publico_interno_confidencial_restringido(owner_conn):
    orden = owner_conn.execute(
        "SELECT unnest(enum_range(NULL::sensitivity_level))::text"
    ).fetchall()
    assert [r[0] for r in orden] == ["publico", "interno", "confidencial", "restringido"]

    ok = owner_conn.execute(
        "SELECT 'publico'::sensitivity_level < 'interno'::sensitivity_level "
        "AND 'interno'::sensitivity_level < 'confidencial'::sensitivity_level "
        "AND 'confidencial'::sensitivity_level < 'restringido'::sensitivity_level"
    ).fetchone()[0]
    assert ok is True


def test_las_etiquetas_solo_se_permiten_en_restringido(owner_conn):
    with pytest.raises(psycopg.errors.CheckViolation), owner_conn.transaction(force_rollback=True):
        owner_conn.execute(
            "INSERT INTO documents (title, dept, sensitivity, acl_tags) "
            "VALUES ('x', 'institucional', 'interno', '{comite_disciplinario}')"
        )


def test_el_trigger_propaga_el_cambio_de_clasificacion_a_los_fragmentos(owner_conn):
    doc = doc_uuid("calificaciones-de-fundamentos-de-seguridad")
    with owner_conn.transaction(force_rollback=True):
        owner_conn.execute("UPDATE documents SET sensitivity = 'interno' WHERE id = %s", (doc,))
        filas = owner_conn.execute(
            "SELECT sensitivity::text FROM chunks WHERE doc_id = %s", (doc,)
        ).fetchall()
    assert filas and all(f[0] == "interno" for f in filas)


def test_un_fragmento_nuevo_hereda_la_clasificacion_del_documento(owner_conn):
    doc = doc_uuid("nomina-individual-sofia-ariza")  # confidencial con dueño
    with owner_conn.transaction(force_rollback=True):
        fila = owner_conn.execute(
            "INSERT INTO chunks (doc_id, chunk_index, content) VALUES (%s, 99, 'texto') "
            "RETURNING dept, sensitivity::text, owner_id::text",
            (doc,),
        ).fetchone()
    assert fila == ("financiera", "confidencial", _USER.format(1))


def test_el_rol_de_aplicacion_no_es_superusuario_ni_ignora_rls(app_conn):
    fila = app_conn.execute(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert fila == (False, False)


def test_el_rol_de_aplicacion_no_lee_usuarios(app_conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT * FROM users")


def test_el_rol_de_aplicacion_solo_inserta_en_auditoria(app_conn):
    with app_conn.transaction(force_rollback=True):
        app_conn.execute(
            "INSERT INTO audit_log (trace_id, query) VALUES (gen_random_uuid(), 'prueba')"
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("SELECT * FROM audit_log")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("UPDATE audit_log SET query = 'x'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("DELETE FROM audit_log")


def test_el_rol_de_auditoria_lee_el_registro():
    with psycopg.connect(postgres_dsn(get_settings(), role="audit"), autocommit=True) as conn:
        conn.execute("SELECT count(*) FROM audit_log").fetchone()
