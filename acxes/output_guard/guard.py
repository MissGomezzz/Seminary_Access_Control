"""Guardia determinista de salida para respuestas generadas por el modelo.

La guardia no concede acceso: el PDP y RLS ya hicieron esa decisión. Su función es
evitar que el texto que sale del sistema reintroduzca marcas de datos, citas inventadas
o identificadores personales que no deben aparecer en la interfaz.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

_DATA_MARKS = re.compile(r"<<<(?:DATOS[^>\n]*|FIN DATOS)>>>", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
# Teléfonos móviles colombianos: 3xx xxx xxxx, continuos o con espacios.
# El prefijo internacional es obligatorio para números que no sean colombianos.
_PHONE = re.compile(
    r"(?<![\d])(?:"
    r"\+57[ \t]?3\d{2}(?:[ \t]?\d{3})?(?:[ \t]?\d{4})"
    r"|3\d{2}(?:[ \t]?\d{3})?(?:[ \t]?\d{4})"
    r"|\+(?:[1-9]\d{0,2})[ \t]?(?:\d{3}[ \t]?\d{3}[ \t]?\d{4})"
    r")(?![\d])"
)
_ID = re.compile(
    r"(?i)\b(?P<label>cc|c\.c\.|documento|identificación)\s*[:#-]?\s*\d{5,}\b"
)
_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:!?])")
_CITATION = re.compile(r"\[([^\[\]\n]{1,80})\]")


@dataclass(frozen=True)
class GuardedText:
    text: str
    redactions: int
    invalid_citations: int


def guard_text(text: str, chunk_ids: Sequence[str]) -> GuardedText:
    """Limpia salida no confiable y conserva únicamente citas de chunks entregados."""
    redactions = 0

    def redact(_match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return "[redactado]"

    allowed = {str(chunk_id) for chunk_id in chunk_ids}
    invalid = 0

    def citation(match: re.Match[str]) -> str:
        nonlocal invalid
        value = match.group(1).strip()
        if value in allowed:
            return f"[{value}]"
        invalid += 1
        return ""

    cleaned = _CITATION.sub(citation, _DATA_MARKS.sub("", text))
    cleaned = _EMAIL.sub(redact, cleaned)
    cleaned = _PHONE.sub(redact, cleaned)

    def redact_id(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return f"{match.group('label')} [redactado]"

    cleaned = _ID.sub(redact_id, cleaned)
    cleaned = _BLANK_LINES.sub("\n\n", cleaned).strip()
    cleaned = _SPACE_BEFORE_PUNCT.sub(r"\1", _SPACES.sub(" ", cleaned))
    return GuardedText(cleaned, redactions, invalid)
