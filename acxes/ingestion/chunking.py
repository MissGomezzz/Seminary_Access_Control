"""Normalización y fragmentación del texto de un documento.

Fragmentos de 500 a 800 tokens con solape de entre el 10 y el 15 por ciento. No hay
tokenizador: los tokens se estiman como palabras por 1,4, una aproximación razonable para el
español (registrada en docs/DESVIACIONES.md). Un documento corto queda en un solo fragmento
aunque tenga menos de 500 tokens. Es determinista.
"""

import math
import re
import unicodedata
from dataclasses import dataclass

TOKENS_PER_WORD = 1.4
MIN_TOKENS = 500
MAX_TOKENS = 800
OVERLAP_MIN_TOKENS = int(MAX_TOKENS * 0.10)
OVERLAP_MAX_TOKENS = int(MAX_TOKENS * 0.15)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * TOKENS_PER_WORD)


def normalize(text: str) -> str:
    """NFC, sin caracteres de control, saltos de línea unificados y espacios colapsados."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = _CONTROL.sub("", text)
    text = re.sub(r"[  ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _units(text: str) -> list[str]:
    """Oraciones, cada una con el separador que la precede (salto de párrafo o espacio).
    Una oración más larga que el máximo se corta por palabras."""
    units: list[str] = []
    for p_index, paragraph in enumerate(text.split("\n\n")):
        for s_index, sentence in enumerate(_SENTENCE_END.split(paragraph)):
            sentence = sentence.strip()
            if not sentence:
                continue
            separator = "" if not units else ("\n\n" if s_index == 0 and p_index > 0 else " ")
            words = sentence.split(" ")
            max_words = int(MAX_TOKENS / TOKENS_PER_WORD)
            for start in range(0, len(words), max_words):
                piece = " ".join(words[start : start + max_words])
                units.append((separator if start == 0 else " ") + piece)
    return units


def chunk_text(text: str) -> list[Chunk]:
    """Divide un texto ya normalizado. Cada fragmento nuevo aporta contenido propio y repite al
    inicio las últimas oraciones del anterior como solape."""
    units = _units(text)
    if not units:
        return []

    chunks: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    has_new = False  # si `current` tiene contenido propio además del solape
    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if current and current_tokens + unit_tokens > MAX_TOKENS:
            if has_new:
                chunks.append(current)
                current = _overlap(current)
            else:
                # La oración no cabe junto al solape: se descarta el solape y no se emite
                # un fragmento que solo repita texto
                current = []
            current_tokens = sum(estimate_tokens(u) for u in current)
            has_new = False
        current.append(unit)
        current_tokens += unit_tokens
        has_new = True
    chunks.append(current)

    return [Chunk(index=i, text="".join(parts).strip()) for i, parts in enumerate(chunks)]


def _overlap(previous: list[str]) -> list[str]:
    """Últimas oraciones del fragmento anterior que caben en el tope de solape."""
    tail: list[str] = []
    total = 0
    for unit in reversed(previous):
        tokens = estimate_tokens(unit)
        if total + tokens > OVERLAP_MAX_TOKENS:
            break
        tail.insert(0, unit)
        total += tokens
    return tail
