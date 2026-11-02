"""Búsqueda híbrida (léxica + vectorial con RRF) de S, contra la base.

La rama vectorial no puede abrir un camino nuevo a los datos: devuelve solo lo que el oráculo
permite, aunque el vector de la consulta sea el de un fragmento no autorizado, y RLS la sigue
filtrando aunque el predicado falte en el WHERE. Ninguna aserción depende de la calidad del
modelo, así que valen igual con el embedder de prueba de CI y con el modelo real.
"""

import json

import psycopg
import pytest

from acxes.config import postgres_dsn
from acxes.ingestion.corpus_plan import doc_uuid, load_plan
from acxes.retrieval.embedding import HashEmbedder, to_pgvector
from acxes.retrieval.lexical import (
    HYBRID_SEARCH_CHUNKS_SQL,
    SECURE_HYBRID_SEARCH_CHUNKS_SQL,
    keywords_to_or_query,
)
from acxes.retrieval.secure import SecureRetrievalService, _predicate_params, _session_variables
from tests.rls.contexts import database_pdp, hybrid_settings, security_context
from tests.rls.oracle import PERSONAS, expected_slugs

pytestmark = pytest.mark.db

ACTA = "acta-del-comite-disciplinario-2026-01"
KEYWORD_SETS = [
    ["nómina", "salario", "devengado", "deducciones", "pago"],
    ["auditoría", "hallazgos", "tesorería", "irregularidad"],
    ["disciplinario", "comité", "sanción", "estudiante"],
    ["presupuesto", "evaluación", "desempeño", "calificaciones"],
    # Sin coincidencias léxicas: solo responde la rama vectorial
    ["zzqx", "wwvy", "kkjh"],
]


@pytest.fixture(scope="module")
def settings():
    return hybrid_settings()


@pytest.fixture(scope="module")
def pdp():
    return database_pdp()


@pytest.fixture(scope="module")
def specs():
    return load_plan()


@pytest.fixture(scope="module")
def slug_by_id(specs) -> dict[str, str]:
    return {str(doc_uuid(s.slug)): s.slug for s in specs}


@pytest.fixture(scope="module")
def acta_vector(settings) -> list[float]:
    """Vector guardado del primer fragmento del acta restringida del comité disciplinario."""
    with psycopg.connect(postgres_dsn(settings), autocommit=True) as conn:
        row = conn.execute(
            "SELECT embedding::text FROM chunks WHERE doc_id = %s ORDER BY chunk_index LIMIT 1",
            (doc_uuid(ACTA),),
        ).fetchone()
    assert row and row[0], "el acta no tiene vector"
    return json.loads(row[0])


class _FixedEmbedder(HashEmbedder):
    """Ataque del vecino más cercano: la consulta es exactamente el vector de un fragmento."""

    def __init__(self, vector: list[float]) -> None:
        super().__init__(len(vector))
        self.vector = vector

    def embed_query(self, text):
        return self.vector


def _slugs(service, pdp, slug_by_id, nombre, keywords) -> list[str]:
    ctx = security_context(nombre, pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    return [slug_by_id[h.doc_id] for h in service.search(ctx, decision, keywords)]


@pytest.mark.parametrize("nombre", list(PERSONAS))
@pytest.mark.parametrize("keywords", KEYWORD_SETS)
def test_la_busqueda_hibrida_no_devuelve_fragmentos_no_autorizados(
    settings, pdp, specs, slug_by_id, nombre, keywords
):
    service = SecureRetrievalService(settings)
    slugs = _slugs(service, pdp, slug_by_id, nombre, keywords)
    assert len(slugs) <= settings.retrieval_k
    assert set(slugs) <= expected_slugs(PERSONAS[nombre], specs)
    # A lo sumo un fragmento por documento
    assert len(set(slugs)) == len(slugs)


@pytest.fixture(scope="module")
def publico(settings, specs) -> tuple[str, list[float]]:
    """Un documento público e institucional, visible para todos, y el vector de su fragmento."""
    slug = next(s.slug for s in specs if s.sensitivity == "publico" and s.dept == "institucional")
    with psycopg.connect(postgres_dsn(settings), autocommit=True) as conn:
        row = conn.execute(
            "SELECT embedding::text FROM chunks WHERE doc_id = %s ORDER BY chunk_index LIMIT 1",
            (doc_uuid(slug),),
        ).fetchone()
    return slug, json.loads(row[0])


def test_la_rama_vectorial_responde_sin_coincidencias_lexicas(settings, pdp, slug_by_id, publico):
    slug, vector = publico
    service = SecureRetrievalService(settings, embedder=_FixedEmbedder(vector))
    assert _slugs(service, pdp, slug_by_id, "Sofía", ["zzqx", "wwvy", "kkjh"])[0] == slug


def test_bajo_el_umbral_la_rama_vectorial_no_devuelve_nada(settings, pdp, slug_by_id, publico):
    """Una consulta sin sentido da "sin resultados" y no los vecinos más cercanos (P12)."""
    _, vector = publico
    lejano = _FixedEmbedder([-x for x in vector])
    umbral = settings.model_copy(update={"embedding_min_similarity": 0.5})
    service = SecureRetrievalService(umbral, embedder=lejano)
    assert _slugs(service, pdp, slug_by_id, "Diego", ["zzqx", "wwvy", "kkjh"]) == []


@pytest.mark.parametrize("nombre", list(PERSONAS))
def test_el_vector_de_un_fragmento_restringido_no_lo_devuelve_sin_etiqueta(
    settings, pdp, specs, slug_by_id, acta_vector, nombre
):
    service = SecureRetrievalService(settings, embedder=_FixedEmbedder(acta_vector))
    slugs = _slugs(service, pdp, slug_by_id, nombre, ["zzqx", "wwvy", "kkjh"])

    assert set(slugs) <= expected_slugs(PERSONAS[nombre], specs)
    if "comite_disciplinario" in PERSONAS[nombre].tags:
        # Con la etiqueta, el propio fragmento es su vecino más cercano
        assert slugs[0] == ACTA
    else:
        assert ACTA not in slugs


def _all_params(settings, vector, keywords) -> dict:
    return {
        "q": keywords_to_or_query(keywords),
        "qv": to_pgvector(vector),
        "n": 10_000,
        "k": 10_000,
        "rrf_k": settings.rrf_k,
        "min_sim": None,
    }


@pytest.mark.parametrize("nombre", list(PERSONAS))
def test_rls_filtra_la_rama_vectorial_aunque_falte_el_predicado(
    settings, pdp, specs, slug_by_id, acta_vector, nombre
):
    """Segunda red: con acxes_app, la consulta híbrida de B1 (sin predicado) solo ve las filas
    que RLS permite según las variables de sesión."""
    ctx = security_context(nombre, pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    params = _all_params(settings, acta_vector, KEYWORD_SETS[0])
    with (
        psycopg.connect(postgres_dsn(settings, role="app")) as conn,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        for name, value in _session_variables(decision).items():
            cur.execute("SELECT set_config(%s, %s, true)", (name, value))
        cur.execute(HYBRID_SEARCH_CHUNKS_SQL, params)
        filas = cur.fetchall()

    slugs = {slug_by_id[str(r[1])] for r in filas}
    assert slugs and slugs <= expected_slugs(PERSONAS[nombre], specs)


@pytest.mark.parametrize("nombre", list(PERSONAS))
def test_el_filtro_hibrido_es_correcto_sin_rls(
    settings, pdp, specs, slug_by_id, acta_vector, nombre
):
    """Con el propietario, que ignora RLS, el predicado devuelve exactamente los documentos
    permitidos del resultado sin filtro, ni más ni menos. Se comparan documentos y no
    fragmentos, porque el fragmento elegido de un documento depende de su posición en cada
    rama, y esa posición cambia al quitar los no autorizados."""
    ctx = security_context(nombre, pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    params = _all_params(settings, acta_vector, KEYWORD_SETS[0])
    with psycopg.connect(postgres_dsn(settings), autocommit=True) as conn:
        todos = conn.execute(HYBRID_SEARCH_CHUNKS_SQL, params).fetchall()
        filtrados = conn.execute(
            SECURE_HYBRID_SEARCH_CHUNKS_SQL, _predicate_params(decision.predicate) | params
        ).fetchall()

    permitidos = expected_slugs(PERSONAS[nombre], specs)
    docs_todos = {slug_by_id[str(r[1])] for r in todos}
    esperados = docs_todos & permitidos
    assert esperados and {slug_by_id[str(r[1])] for r in filtrados} == esperados
    assert len(esperados) < len(docs_todos)
