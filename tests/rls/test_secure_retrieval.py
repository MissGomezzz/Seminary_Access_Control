"""Recuperación filtrada sin agente (etapa 3), contra la base.

Criterio de hecho: la misma consulta con tres SecurityContext distintos devuelve tres
conjuntos distintos y correctos, y el sistema deniega cuando el PDP falla. Correcto significa
contenido en lo que el oráculo permite a esa persona.
"""

from uuid import uuid4

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.ingestion.corpus_plan import doc_uuid, load_plan
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.pdp.subject_store import PostgresSubjectStore
from acxes.retrieval.lexical import (
    SEARCH_CHUNKS_SQL,
    SECURE_SEARCH_CHUNKS_SQL,
    keywords_to_or_query,
)
from acxes.retrieval.secure import (
    RetrievalDenied,
    SecureRetrievalService,
    _predicate_params,
)
from tests.rls.contexts import database_pdp, security_context
from tests.rls.oracle import PERSONAS, expected_slugs

pytestmark = pytest.mark.db

NOMINA_KEYWORDS = ["nómina", "salario", "devengado", "deducciones", "pago"]
# Consulta del criterio de hecho. Con k = 5 produce un conjunto distinto por rol
CRITERIO_KEYWORDS = ["evaluación", "desempeño", "metas", "competencias"]


@pytest.fixture(scope="module")
def pdp() -> PolicyDecisionPoint:
    return database_pdp()


@pytest.fixture(scope="module")
def service() -> SecureRetrievalService:
    return SecureRetrievalService(get_settings())


@pytest.fixture(scope="module")
def specs():
    return load_plan()


@pytest.fixture(scope="module")
def slug_by_id(specs) -> dict[str, str]:
    return {str(doc_uuid(s.slug)): s.slug for s in specs}


def _allowed(pdp, nombre, action="search"):
    ctx = security_context(nombre, pdp)
    return ctx, pdp.evaluate(ctx, action, "documentos")


def _search_slugs(service, pdp, slug_by_id, nombre, keywords) -> list[str]:
    ctx, decision = _allowed(pdp, nombre)
    return [slug_by_id[h.doc_id] for h in service.search(ctx, decision, keywords)]


def test_misma_consulta_tres_contextos_tres_conjuntos_correctos(service, pdp, specs, slug_by_id):
    resultados = {}
    for nombre in ("Sofía", "Laura", "Diego"):
        slugs = _search_slugs(service, pdp, slug_by_id, nombre, CRITERIO_KEYWORDS)
        assert slugs, f"{nombre} no obtuvo resultados"
        assert len(slugs) <= get_settings().retrieval_k
        assert set(slugs) <= expected_slugs(PERSONAS[nombre], specs)
        resultados[nombre] = frozenset(slugs)

    assert len(set(resultados.values())) == 3
    # La supervisora recibe su propia evaluación y la empleada, a lo sumo, la suya
    assert "evaluacion-de-desempeno-laura-martinez" in resultados["Laura"]
    assert {s for s in resultados["Sofía"] if s.startswith("evaluacion-de-desempeno-")} <= {
        "evaluacion-de-desempeno-sofia-ariza"
    }


@pytest.mark.parametrize("nombre", list(PERSONAS))
@pytest.mark.parametrize(
    "keywords",
    [
        NOMINA_KEYWORDS,
        ["auditoría", "hallazgos", "tesorería", "irregularidad"],
        ["disciplinario", "comité", "sanción", "estudiante"],
        ["presupuesto", "evaluación", "desempeño", "calificaciones"],
    ],
)
def test_ninguna_busqueda_devuelve_fragmentos_no_autorizados(
    service, pdp, specs, slug_by_id, nombre, keywords
):
    slugs = _search_slugs(service, pdp, slug_by_id, nombre, keywords)
    assert set(slugs) <= expected_slugs(PERSONAS[nombre], specs)


def test_leer_documento_autorizado(service, pdp):
    ctx, decision = _allowed(pdp, "Sofía", "read")
    doc = service.read_document(ctx, decision, doc_uuid("nomina-individual-sofia-ariza"))

    assert doc is not None and doc.chunks
    assert all(c.doc_id == doc.doc_id for c in doc.chunks)


def test_no_autorizado_e_inexistente_son_indistinguibles(service, pdp):
    ctx, decision = _allowed(pdp, "Sofía", "read")
    ajeno = service.read_document(ctx, decision, doc_uuid("nomina-individual-laura-martinez"))
    inexistente = service.read_document(ctx, decision, uuid4())

    assert ajeno is None and inexistente is None


def test_restringido_solo_por_etiqueta_al_leer(service, pdp):
    acta = doc_uuid("acta-del-comite-disciplinario-2026-01")
    ctx, decision = _allowed(pdp, "Carlos", "read")
    assert service.read_document(ctx, decision, acta) is not None
    ctx, decision = _allowed(pdp, "Diego", "read")
    assert service.read_document(ctx, decision, acta) is None


class _NoConnect:
    calls = 0

    def __call__(self, *_):
        self.calls += 1
        raise AssertionError("no debe abrir conexión")


def test_con_denegacion_del_pdp_no_se_abre_conexion(pdp):
    connect = _NoConnect()
    service = SecureRetrievalService(get_settings(), connect=connect)
    # Un usuario que no existe en la base
    ctx = security_context("Sofía", pdp).model_copy(update={"user_id": uuid4()})
    decision = pdp.evaluate(ctx, "search", "documentos")
    assert decision.reason == "unknown_user"

    with pytest.raises(RetrievalDenied):
        service.search(ctx, decision, NOMINA_KEYWORDS)
    with pytest.raises(RetrievalDenied):
        service.read_document(ctx, decision, doc_uuid("nomina-individual-sofia-ariza"))
    assert connect.calls == 0


def test_con_pdp_sin_politica_no_se_abre_conexion(pdp, tmp_path):
    connect = _NoConnect()
    service = SecureRetrievalService(get_settings(), connect=connect)
    roto = PolicyDecisionPoint(PostgresSubjectStore(get_settings()), tmp_path / "2026-09-21.1.yaml")
    ctx = security_context("Diego", pdp)
    decision = roto.evaluate(ctx, "search", "documentos")

    with pytest.raises(RetrievalDenied):
        service.search(ctx, decision, NOMINA_KEYWORDS)
    assert connect.calls == 0


def test_una_decision_de_otra_persona_se_rechaza(service, pdp):
    _, decision_diego = _allowed(pdp, "Diego")
    ctx_sofia = security_context("Sofía", pdp)

    with pytest.raises(RetrievalDenied):
        service.search(ctx_sofia, decision_diego, NOMINA_KEYWORDS)


def test_el_servicio_usa_el_rol_de_aplicacion_sin_privilegios(pdp):
    """El servicio abre su conexión con acxes_app, que no es superusuario ni ignora RLS."""
    usados = []

    def spy(dsn):
        conn = psycopg.connect(dsn)
        usados.append(
            conn.execute(
                "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            ).fetchone()
        )
        conn.rollback()
        return conn

    service = SecureRetrievalService(get_settings(), connect=spy)
    ctx, decision = _allowed(pdp, "Sofía")
    service.search(ctx, decision, NOMINA_KEYWORDS)

    assert usados == [("acxes_app", False, False)]


@pytest.mark.parametrize("nombre", list(PERSONAS))
def test_el_filtro_de_la_consulta_es_correcto_sin_rls(pdp, specs, slug_by_id, nombre):
    """Defensa en profundidad: con el propietario, que ignora RLS, el WHERE del predicado
    devuelve exactamente los resultados sin filtro que el oráculo permite, ni más ni menos."""
    _, decision = _allowed(pdp, nombre)
    base = {
        "q": keywords_to_or_query(NOMINA_KEYWORDS + ["auditoría", "disciplinario", "presupuesto"]),
        "k": 1000,
    }
    with psycopg.connect(postgres_dsn(get_settings()), autocommit=True) as conn:
        todos = conn.execute(SEARCH_CHUNKS_SQL, base).fetchall()
        filtrados = conn.execute(
            SECURE_SEARCH_CHUNKS_SQL, _predicate_params(decision.predicate) | base
        ).fetchall()

    permitidos = expected_slugs(PERSONAS[nombre], specs)
    esperados = {r[0] for r in todos if slug_by_id[str(r[1])] in permitidos}
    assert esperados and {r[0] for r in filtrados} == esperados
    assert len(esperados) < len(todos)
