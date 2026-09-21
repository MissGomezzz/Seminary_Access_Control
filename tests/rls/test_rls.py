"""Pruebas de RLS directas contra la base, sin pasar por la aplicación.

Se conectan como `acxes_app` y fijan las variables de sesión que el servicio de
recuperación de S fijaría a partir del predicado del PDP (docs/VARIABLES_SESION.md).
Los conjuntos esperados se derivan de documents/MATRIZ_ACCESO.md y están escritos a mano,
independientes de la política, para que un error en ella no se copie a la prueba.
Requieren `python -m acxes.db.apply`.
"""

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn

pytestmark = pytest.mark.db

_USER = "00000000-0000-4000-a000-00000000000{}"
_INSTITUCIONAL = set(range(1, 8))  # D01 a D07, públicos e internos de la dependencia institucional


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

# Documentos visibles por usuario, por número de documento del seed
ESPERADO = {
    "Sofía": (SOFIA, _INSTITUCIONAL | {13, 14, 16}),
    "Belén": (BELEN, _INSTITUCIONAL | {13, 14, 17}),
    "Ángela": (ANGELA, _INSTITUCIONAL | {8, 9, 11, 18}),
    "Laura": (LAURA, _INSTITUCIONAL | {13, 14, 15, 16, 17, 18, 19, 20, 21, 22}),
    "Carlos": (CARLOS, _INSTITUCIONAL | {8, 9, 10, 11, 12, 20}),
    "Diego": (DIEGO, _INSTITUCIONAL | {8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21}),
}


@pytest.fixture(scope="module")
def titles() -> dict[int, str]:
    """Título por número de documento. El número son los dos últimos dígitos del id."""
    with psycopg.connect(postgres_dsn(get_settings())) as conn:
        rows = conn.execute("SELECT right(id::text, 2)::int, title FROM documents").fetchall()
    return dict(rows)


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


@pytest.mark.parametrize("nombre", list(ESPERADO))
def test_cada_usuario_ve_exactamente_lo_que_dice_la_matriz(app_conn, titles, nombre):
    ctx, numeros = ESPERADO[nombre]

    vistos = {title for _, title in _visible(app_conn, ctx)}

    assert vistos == {titles[n] for n in numeros}


@pytest.mark.parametrize("nombre", list(ESPERADO))
def test_los_fragmentos_siguen_a_sus_documentos(app_conn, nombre):
    ctx, _ = ESPERADO[nombre]
    with app_conn.transaction():
        for name, value in ctx.items():
            app_conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        doc_ids = {r[0] for r in app_conn.execute("SELECT id FROM documents").fetchall()}
        chunk_docs = {r[0] for r in app_conn.execute("SELECT doc_id FROM chunks").fetchall()}

    assert chunk_docs == doc_ids


def test_sin_variables_de_sesion_no_hay_filas(app_conn):
    assert _visible(app_conn, {}) == []
    assert _visible(app_conn, {}, table="chunks") == []


def test_variables_vacias_no_hay_filas(app_conn):
    ctx = {name: "" for name in SOFIA}
    assert _visible(app_conn, ctx) == []


def test_falta_el_nivel_maximo_y_no_hay_filas_por_dependencia(app_conn):
    ctx = {"app.allowed_depts": "institucional,academica,financiera"}
    assert _visible(app_conn, ctx) == []


def test_un_tope_restringido_no_concede_el_nivel_restringido(app_conn, titles):
    """Defensa en profundidad: aunque el PDP nunca lo emite, RLS no lo concede por nivel."""
    ctx = dict(DIEGO, **{"app.clearance": "restringido"})
    vistos = {title for _, title in _visible(app_conn, ctx)}

    assert titles[12] not in vistos and titles[22] not in vistos and titles[23] not in vistos


def test_restringido_solo_por_etiqueta_y_sin_etiquetas_no_lo_ve_nadie(app_conn, titles):
    ctx = dict(DIEGO, **{"app.acl_tags": "comite_disciplinario,auditoria_interna"})
    vistos = {title for _, title in _visible(app_conn, ctx)}

    assert titles[12] in vistos and titles[22] in vistos
    assert titles[23] not in vistos


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


def test_el_trigger_propaga_el_cambio_de_clasificacion_a_los_fragmentos(owner_conn, titles):
    doc = "00000000-0000-4000-b000-000000000010"
    with owner_conn.transaction(force_rollback=True):
        owner_conn.execute("UPDATE documents SET sensitivity = 'interno' WHERE id = %s", (doc,))
        filas = owner_conn.execute(
            "SELECT sensitivity::text FROM chunks WHERE doc_id = %s", (doc,)
        ).fetchall()
    assert filas and all(f[0] == "interno" for f in filas)


def test_un_fragmento_nuevo_hereda_la_clasificacion_del_documento(owner_conn):
    doc = "00000000-0000-4000-b000-000000000016"  # nómina de Sofía, confidencial con dueño
    with owner_conn.transaction(force_rollback=True):
        fila = owner_conn.execute(
            "INSERT INTO chunks (doc_id, chunk_index, content) VALUES (%s, 9, 'texto') "
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
