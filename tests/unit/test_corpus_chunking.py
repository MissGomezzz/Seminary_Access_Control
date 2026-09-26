"""Pruebas de normalización, fragmentación y canarios. Sin base de datos ni red."""

from itertools import pairwise

from acxes.ingestion.canary import CANARY_RE, PREFIX, canary_for
from acxes.ingestion.chunking import (
    MAX_TOKENS,
    OVERLAP_MAX_TOKENS,
    chunk_text,
    estimate_tokens,
    normalize,
)


def _texto(oraciones: int, palabras: int = 25) -> str:
    """Párrafos de cinco oraciones con palabras únicas, para detectar pérdidas y duplicados."""
    partes = []
    for i in range(oraciones):
        cuerpo = " ".join(f"p{i}x{j}" for j in range(palabras - 1))
        partes.append(f"Oración {i} {cuerpo}.")
    parrafos = [" ".join(partes[k : k + 5]) for k in range(0, len(partes), 5)]
    return "\n\n".join(parrafos)


def test_normalize_unifica_espacios_saltos_y_caracteres_de_control():
    crudo = "Hola\x00  mundo\r\n\r\n\r\n\r\nSegundo\tpárrafo    fin "
    assert normalize(crudo) == "Hola mundo\n\nSegundo párrafo fin"


def test_normalize_compone_en_nfc():
    # 'a' seguida de un acento combinante debe quedar como el carácter compuesto 'á'
    resultado = normalize("Nominá")
    assert resultado == "Nominá" and len(resultado) == 6


def test_un_texto_corto_es_un_solo_fragmento_aunque_tenga_menos_de_500_tokens():
    texto = _texto(4)
    chunks = chunk_text(texto)
    assert len(chunks) == 1 and chunks[0].index == 0
    assert estimate_tokens(chunks[0].text) < 500


def test_un_texto_vacio_no_produce_fragmentos():
    assert chunk_text("") == []


def test_ningun_fragmento_supera_el_maximo():
    for chunk in chunk_text(_texto(120)):
        assert estimate_tokens(chunk.text) <= MAX_TOKENS


def test_los_fragmentos_intermedios_estan_entre_500_y_800_tokens():
    chunks = chunk_text(_texto(200))
    assert len(chunks) >= 3
    for chunk in chunks[:-1]:
        assert 500 <= estimate_tokens(chunk.text) <= MAX_TOKENS


def test_el_solape_esta_entre_el_10_y_el_15_por_ciento():
    chunks = chunk_text(_texto(200))
    for anterior, siguiente in pairwise(chunks):
        # Oraciones que el siguiente repite del final del anterior
        repetidas = [
            s for s in siguiente.text.replace("\n\n", " ").split(". ") if s and s in anterior.text
        ]
        solape = estimate_tokens(". ".join(repetidas))
        assert 80 <= solape <= OVERLAP_MAX_TOKENS + 5


def test_no_se_pierde_ninguna_palabra():
    texto = _texto(150)
    chunks = chunk_text(texto)
    unidas = " ".join(c.text for c in chunks)
    for palabra in texto.split():
        assert palabra in unidas


def test_ningun_fragmento_es_solo_solape():
    chunks = chunk_text(_texto(150))
    for anterior, siguiente in pairwise(chunks):
        assert siguiente.text.strip() not in anterior.text


def test_una_oracion_gigante_se_corta_por_palabras_y_respeta_el_maximo():
    gigante = " ".join(f"w{i}" for i in range(2000)) + "."
    chunks = chunk_text(gigante)
    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= MAX_TOKENS for c in chunks)


def test_la_fragmentacion_es_determinista():
    texto = _texto(120)
    assert chunk_text(texto) == chunk_text(texto)


def test_el_canario_es_reproducible_unico_y_con_el_formato_esperado():
    assert canary_for("acta-1") == canary_for("acta-1")
    assert canary_for("acta-1") != canary_for("acta-2")
    canario = canary_for("acta-1")
    assert canario.startswith(PREFIX) and CANARY_RE.fullmatch(canario)


def test_el_canario_no_usa_simbolos_ambiguos():
    for i in range(200):
        sufijo = canary_for(f"doc-{i}")[len(PREFIX) :]
        assert not set("IO01") & set(sufijo)
