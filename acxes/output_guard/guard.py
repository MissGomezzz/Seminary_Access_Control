"""Guardia de salida: citas verificables y controles de contenido residual."""

import re
from dataclasses import dataclass

_CANARY = re.compile(r"\bACXES-CNRY-[A-Z0-9]{8}\b", re.IGNORECASE)
_CITATION = re.compile(r"\[([^\[\]]+)\]")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_ID_NUMBER = re.compile(r"(?<!\w)(?:CC|TI|NIT)\s*[:#-]?\s*\d[\d.-]{5,}(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class GuardResult:
    text: str
    status: str
    reason: str = ""


def guard_output(text: str, chunk_ids: tuple[str, ...] | list[str] = ()) -> GuardResult:
    """Exige citas de todos los chunks entregados, rechaza fuentes fantasma y canarios."""
    if _CANARY.search(text):
        return GuardResult(_blocked(), "blocked", "canario")
    expected = set(chunk_ids)
    if expected and not all(chunk_id in text for chunk_id in expected):
        return GuardResult(_blocked(), "blocked", "citas obligatorias")
    cited = {match.strip() for match in _CITATION.findall(text)}
    if cited - expected:
        return GuardResult(_blocked(), "blocked", "fuente inexistente")
    redacted = _EMAIL.sub("[PII redactada]", text)
    redacted = _PHONE.sub("[PII redactada]", redacted)
    redacted = _ID_NUMBER.sub("[PII redactada]", redacted)
    return GuardResult(redacted, "redacted" if redacted != text else "passed")


def _blocked() -> str:
    return "No fue posible validar la respuesta con las fuentes autorizadas."
