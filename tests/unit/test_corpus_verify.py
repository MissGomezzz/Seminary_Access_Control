"""Pruebas de la verificación del corpus previa a la ingesta. Sin base de datos."""

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from acxes.ingestion.corpus_plan import (
    DOCS_DIR,
    GeneratedDoc,
    load_generated,
    load_plan,
    parse_salaries,
)
from acxes.ingestion.load import CorpusError, payroll_salary, verify_corpus


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    destino = tmp_path / "docs"
    shutil.copytree(DOCS_DIR, destino)
    return destino


def _un_slug() -> str:
    return load_plan()[0].slug


def test_el_corpus_versionado_es_valido():
    verify_corpus()


@pytest.mark.parametrize("contenido", ["", "﻿\n\n", "no es json", "{}"])
def test_un_archivo_vacio_o_invalido_falla_y_nombra_el_documento(docs, contenido):
    slug = _un_slug()
    (docs / f"{slug}.json").write_text(contenido, encoding="utf-8")
    with pytest.raises(CorpusError, match=slug):
        verify_corpus(docs)


def test_un_cuerpo_con_otro_slug_falla(docs):
    slug, otro = load_plan()[0].slug, load_plan()[1].slug
    contenido = (docs / f"{otro}.json").read_text(encoding="utf-8")
    (docs / f"{slug}.json").write_text(contenido, encoding="utf-8")
    with pytest.raises(CorpusError, match=slug):
        verify_corpus(docs)


def test_un_cuerpo_ausente_falla(docs):
    (docs / f"{_un_slug()}.json").unlink()
    with pytest.raises(CorpusError, match="Faltan 1"):
        verify_corpus(docs)


def _reescribir(docs: Path, slug: str, cambio) -> None:
    ruta = docs / f"{slug}.json"
    doc = GeneratedDoc.model_validate_json(ruta.read_text(encoding="utf-8"))
    ruta.write_text(
        doc.model_copy(update={"body": cambio(doc.body)}).model_dump_json(), encoding="utf-8"
    )


NOMINA = "nomina-individual-sofia-ariza"


@pytest.mark.parametrize(
    "cambio",
    [
        lambda b: b.replace("Salario mensual: $4.200.000", "Salario mensual: $4.300.000"),
        lambda b: b.replace("Salario mensual: $4.200.000", "Salario de $4.200.000"),
        lambda b: b + "\n\nSalario mensual: $4.200.000",
    ],
    ids=["otro-salario", "sin-salario", "salario-repetido"],
)
def test_una_nomina_sin_exactamente_el_salario_del_plan_falla(docs, cambio):
    _reescribir(docs, NOMINA, cambio)
    with pytest.raises(CorpusError, match=NOMINA):
        verify_corpus(docs)


def test_el_salario_sale_del_cuerpo_de_cada_nomina():
    nominas = [s for s in load_plan() if s.doc_type == "nomina"]
    assert len(nominas) == 6
    for spec in nominas:
        cuerpo = load_generated(spec.slug).body
        assert payroll_salary(spec, cuerpo) == parse_salaries(spec.hint)[0]
    otro = next(s for s in load_plan() if s.doc_type != "nomina")
    assert payroll_salary(otro, "Salario mensual: $1.000.000") is None


def test_parse_salaries_lee_pesos_con_puntos_de_miles():
    assert parse_salaries("Salario mensual: $4.200.000 y Salario mensual: $950.000") == [
        Decimal(4200000),
        Decimal(950000),
    ]
