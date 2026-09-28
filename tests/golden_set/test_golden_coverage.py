"""Golden set de recuperación filtrada (etapa 3), contra la base.

Falla si el golden set pide algo no autorizado o si la recuperación devuelve un documento no
autorizado. La cobertura (al menos un esperado entre los k primeros) se reporta sin umbral,
porque el plan pide medirla y muchos cuerpos del corpus son cortos. Para verla:
`pytest tests/golden_set -s`.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field

from acxes.config import get_settings
from acxes.ingestion.corpus_plan import doc_uuid, load_plan
from acxes.orchestrator.tool_catalog import BuscarDocumentos
from acxes.retrieval.secure import SecureRetrievalService
from tests.rls.contexts import database_pdp, security_context
from tests.rls.oracle import PERSONAS, expected_slugs

GOLDEN_PATH = Path(__file__).with_name("golden.yaml")


class GoldenQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    persona: str
    question: str
    keywords: list[str]
    expected: list[str] = Field(min_length=1)


def load_golden() -> list[GoldenQuestion]:
    raw = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [GoldenQuestion.model_validate(q) for q in raw["questions"]]


GOLDEN = load_golden()


@pytest.fixture(scope="module")
def specs():
    return load_plan()


def test_el_golden_set_es_legitimo(specs):
    slugs = {s.slug for s in specs}
    for q in GOLDEN:
        assert q.persona in PERSONAS
        # Las palabras clave cumplen el esquema cerrado de la herramienta
        BuscarDocumentos(keywords=q.keywords)
        assert set(q.expected) <= slugs, q.question
        assert set(q.expected) <= expected_slugs(PERSONAS[q.persona], specs), q.question


def test_unas_diez_preguntas_por_rol():
    por_rol: dict[str, int] = {}
    for q in GOLDEN:
        role = PERSONAS[q.persona].role
        por_rol[role] = por_rol.get(role, 0) + 1
    assert set(por_rol) == {"empleado", "supervisor", "administrador"}
    assert all(n >= 10 for n in por_rol.values())


@pytest.mark.db
def test_cobertura_y_ausencia_de_fugas(specs):
    pdp = database_pdp()
    service = SecureRetrievalService(get_settings())
    slug_by_id = {str(doc_uuid(s.slug)): s.slug for s in specs}

    aciertos: dict[str, list[bool]] = {}
    fallos = []
    for q in GOLDEN:
        ctx = security_context(q.persona, pdp)
        decision = pdp.evaluate(ctx, "search", "documentos")
        slugs = [slug_by_id[h.doc_id] for h in service.search(ctx, decision, q.keywords)]

        assert set(slugs) <= expected_slugs(PERSONAS[q.persona], specs), q.question
        acierto = bool(set(slugs) & set(q.expected))
        aciertos.setdefault(PERSONAS[q.persona].role, []).append(acierto)
        if not acierto:
            fallos.append(f"  {q.persona}: {q.question} -> {slugs}")

    print("\nCobertura del golden set (al menos un esperado en los k primeros):")
    for role, valores in aciertos.items():
        print(f"  {role}: {sum(valores)}/{len(valores)}")
    if fallos:
        print("Sin acierto:\n" + "\n".join(fallos))
