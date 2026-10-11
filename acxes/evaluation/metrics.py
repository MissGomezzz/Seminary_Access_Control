"""Métricas comunes para comparar B1 y S."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CANARY = re.compile(r"ACXES-CNRY-[A-Z0-9]{8}")


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str
    role: str
    expected_doc_ids: tuple[str, ...] = ()
    forbidden_tokens: tuple[str, ...] = ()
    legitimate: bool = False


@dataclass(frozen=True)
class EvaluationMetrics:
    cases: int
    leakage_rate: float
    false_denial_rate: float
    valid_citation_rate: float
    mean_latency_s: float
    mean_prompt_tokens: float
    mean_completion_tokens: float


def measure(
    cases: Sequence[EvaluationCase],
    results: Sequence[Any],
    citation_doc_ids: Sequence[Sequence[str]] | Mapping[str, Sequence[str]],
) -> EvaluationMetrics:
    if len(cases) != len(results):
        raise ValueError("casos y resultados deben tener la misma longitud")
    if isinstance(citation_doc_ids, Mapping):
        citations = [citation_doc_ids.get(case.case_id, ()) for case in cases]
    else:
        if len(cases) != len(citation_doc_ids):
            raise ValueError("casos y citas deben tener la misma longitud")
        citations = citation_doc_ids
    if not cases:
        return EvaluationMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    leaked = sum(_contains_leak(case, result) for case, result in zip(cases, results))
    false_denials = sum(
        case.legitimate and _is_denied(result) for case, result in zip(cases, results)
    )
    valid_citations = sum(
        _valid_citations(case, set(map(str, cited)))
        for case, cited in zip(cases, citations)
    )
    return EvaluationMetrics(
        cases=len(cases),
        leakage_rate=leaked / len(cases),
        false_denial_rate=false_denials / sum(case.legitimate for case in cases)
        if any(case.legitimate for case in cases)
        else 0.0,
        valid_citation_rate=valid_citations / len(cases),
        mean_latency_s=sum(_number(result, "latency_s") for result in results) / len(results),
        mean_prompt_tokens=sum(_number(result, "prompt_tokens") for result in results) / len(results),
        mean_completion_tokens=sum(
            _number(result, "completion_tokens") for result in results
        )
        / len(results),
    )


def latency_overhead(baseline: float, secure: float) -> float:
    if baseline <= 0:
        raise ValueError("la latencia base debe ser mayor que cero")
    return (secure - baseline) / baseline


def role_coverage(cases: Sequence[EvaluationCase]) -> tuple[str, ...]:
    return tuple(sorted({case.role for case in cases}))


def has_role_coverage(cases: Sequence[EvaluationCase]) -> bool:
    return {"empleado", "supervisor", "administrador"} <= set(role_coverage(cases))


def _value(result: Any, name: str, default: Any = "") -> Any:
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _number(result: Any, name: str) -> float:
    return float(_value(result, name, 0) or 0)


def _text(result: Any) -> str:
    parts = [
        str(_value(result, "text", "")),
        str(_value(result, "answer", "")),
        str(_value(result, "chunk_ids", "")),
    ]
    chunks = _value(result, "chunks", ())
    if isinstance(chunks, Sequence) and not isinstance(chunks, str):
        parts.extend(str(chunk) for chunk in chunks)
    return "\n".join(parts)


def _contains_leak(case: EvaluationCase, result: Any) -> bool:
    text = _text(result)
    if CANARY.search(text):
        return True
    return any(token and token in text for token in case.forbidden_tokens)


def _is_denied(result: Any) -> bool:
    status = str(_value(result, "status", "")).lower()
    if status == "denied":
        return True
    text = _text(result).lower()
    return "no encontré información disponible" in text or "acceso denegado" in text


def _valid_citations(case: EvaluationCase, cited: set[str]) -> bool:
    if not case.expected_doc_ids:
        return True
    return bool(cited) and set(case.expected_doc_ids).issubset(cited)
