"""Pruebas de la verificación del corpus previa a la ingesta. Sin base de datos."""

import shutil
from pathlib import Path

import pytest

from acxes.ingestion.corpus_plan import DOCS_DIR, load_plan
from acxes.ingestion.load import CorpusError, verify_corpus


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
