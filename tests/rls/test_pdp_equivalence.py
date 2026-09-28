"""Equivalencia entre el predicado del PDP y la política RLS (etapa 3).

Para cada persona y cada fragmento cargado se comparan tres decisiones independientes: la
del predicado del PDP evaluado en Python, la de RLS vista como `acxes_app` con las
variables de sesión que fija el servicio de recuperación, y la del oráculo escrito a mano
desde la matriz. Las tres deben coincidir fragmento por fragmento.
"""

from uuid import UUID

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.ingestion.corpus_plan import doc_uuid, load_plan
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.retrieval.secure import _session_variables
from tests.rls.contexts import database_pdp, security_context
from tests.rls.oracle import PERSONAS, visible

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def pdp() -> PolicyDecisionPoint:
    return database_pdp()


@pytest.fixture(scope="module")
def chunks() -> list[tuple]:
    """Todos los fragmentos con su clasificación, leídos con el propietario, que ignora RLS."""
    with psycopg.connect(postgres_dsn(get_settings()), autocommit=True) as conn:
        return conn.execute(
            "SELECT id, doc_id, dept, sensitivity::text, owner_id, acl_tags FROM chunks"
        ).fetchall()


@pytest.fixture(scope="module")
def spec_by_doc() -> dict:
    return {doc_uuid(s.slug): s for s in load_plan()}


def _rls_visible_chunks(variables: dict[str, str]) -> set[UUID]:
    dsn = postgres_dsn(get_settings(), role="app")
    with psycopg.connect(dsn, autocommit=True) as conn, conn.transaction():
        for name, value in variables.items():
            conn.execute("SELECT set_config(%s, %s, true)", (name, value))
        return {r[0] for r in conn.execute("SELECT id FROM chunks").fetchall()}


def test_se_cargaron_todos_los_fragmentos(chunks, spec_by_doc):
    assert len(chunks) > 0
    assert {c[1] for c in chunks} == set(spec_by_doc)


@pytest.mark.parametrize("nombre", list(PERSONAS))
def test_pdp_rls_y_oraculo_coinciden_en_cada_fragmento(pdp, chunks, spec_by_doc, nombre):
    ctx = security_context(nombre, pdp)
    decision = pdp.evaluate(ctx, "search", "documentos")
    assert decision.allowed

    por_rls = _rls_visible_chunks(_session_variables(decision))
    diferencias = []
    for chunk_id, doc_id, dept, sensitivity, owner_id, acl_tags in chunks:
        pdp_ve = decision.predicate.allows(dept, sensitivity, owner_id, tuple(acl_tags))
        rls_ve = chunk_id in por_rls
        oraculo_ve = visible(PERSONAS[nombre], spec_by_doc[doc_id])
        if not pdp_ve == rls_ve == oraculo_ve:
            diferencias.append((spec_by_doc[doc_id].slug, pdp_ve, rls_ve, oraculo_ve))

    assert diferencias == []
    # La persona ve algo y no lo ve todo, para que la comparación no sea trivial
    assert 0 < len(por_rls) < len(chunks)
