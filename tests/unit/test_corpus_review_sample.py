"""Pruebas de la muestra de revisión manual. Sin base de datos ni red."""

from collections import Counter

from acxes.ingestion.corpus_plan import load_plan
from acxes.ingestion.review_sample import (
    REVIEW_PATH,
    pick_sample,
    render,
    sample_size,
)


def test_la_muestra_es_el_20_por_ciento_y_es_reproducible():
    specs = load_plan()
    muestra = pick_sample(specs)
    assert len(muestra) == sample_size(150) == 30
    assert [s.slug for s in muestra] == [s.slug for s in pick_sample(specs)]
    assert len({s.slug for s in muestra}) == 30


def test_la_muestra_cubre_cada_dependencia_y_nivel():
    specs = load_plan()
    todas = {(s.dept, s.sensitivity) for s in specs}
    assert {(s.dept, s.sensitivity) for s in pick_sample(specs)} == todas


def test_la_muestra_incluye_senuelos_inyecciones_y_documentos_con_dueno():
    tipos = Counter(s.kind for s in pick_sample(load_plan()))
    assert tipos["senuelo"] >= 2 and tipos["inyeccion"] >= 2
    assert sum(1 for s in pick_sample(load_plan()) if s.owner) >= 3


def test_la_muestra_pesa_mas_lo_reservado_que_su_proporcion_en_el_corpus():
    specs = load_plan()
    reservados = sum(1 for s in specs if s.carries_canary) / len(specs)
    en_muestra = sum(1 for s in pick_sample(specs) if s.carries_canary) / 30
    assert en_muestra > reservados


def test_la_semilla_cambia_la_muestra():
    specs = load_plan()
    assert {s.slug for s in pick_sample(specs, seed=1)} != {s.slug for s in pick_sample(specs)}


def test_la_lista_de_control_versionada_corresponde_a_la_muestra():
    """Si el plan cambia, REVISION.md debe regenerarse: la revisión es sobre esta muestra."""
    specs = load_plan()
    assert REVIEW_PATH.read_text(encoding="utf-8") == render(pick_sample(specs), len(specs))
