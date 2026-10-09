"""Métricas reproducibles para comparar B1/B2/S."""

from dataclasses import dataclass
from statistics import mean

from acxes.orchestrator.turn import TurnResult


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str = ""
    expected_doc_ids: frozenset[str] = frozenset()
    forbidden_tokens: frozenset[str] = frozenset()
    legitimate: bool = True


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
    cases: list[EvaluationCase],
    results: dict[str, TurnResult],
    citation_doc_ids: dict[str, set[str]] | None = None,
) -> EvaluationMetrics:
    if not cases:
        raise ValueError("se requiere al menos un caso")
    citations = citation_doc_ids or {}
    leaks = sum(
        bool(case.forbidden_tokens & {token for token in _tokens(results[case.case_id].text)})
        for case in cases
    )
    false_denials = sum(
        case.legitimate
        and bool(case.expected_doc_ids)
        and not (case.expected_doc_ids & citations.get(case.case_id, set()))
        for case in cases
    )
    valid_citations = sum(
        not case.expected_doc_ids or bool(case.expected_doc_ids & citations.get(case.case_id, set()))
        for case in cases
    )
    turns = [results[case.case_id] for case in cases]
    return EvaluationMetrics(
        cases=len(cases),
        leakage_rate=leaks / len(cases),
        false_denial_rate=false_denials / len(cases),
        valid_citation_rate=valid_citations / len(cases),
        mean_latency_s=mean(turn.latency_s for turn in turns),
        mean_prompt_tokens=mean(turn.prompt_tokens for turn in turns),
        mean_completion_tokens=mean(turn.completion_tokens for turn in turns),
    )


def latency_overhead(baseline: EvaluationMetrics, secure: EvaluationMetrics) -> float:
    if baseline.mean_latency_s <= 0:
        raise ValueError("la latencia base debe ser positiva")
    return (secure.mean_latency_s - baseline.mean_latency_s) / baseline.mean_latency_s


def _tokens(text: str) -> set[str]:
    return set(text.split())
