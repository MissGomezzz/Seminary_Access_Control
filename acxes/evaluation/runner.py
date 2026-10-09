"""Arnés pequeño para ejecutar el mismo conjunto de casos contra un agente."""

from collections.abc import Callable

from acxes.evaluation.metrics import EvaluationCase, EvaluationMetrics, measure
from acxes.orchestrator.turn import TurnResult


def run_cases(
    cases: list[EvaluationCase],
    responder: Callable[[str], TurnResult],
) -> tuple[EvaluationMetrics, dict[str, TurnResult]]:
    results = {case.case_id: responder(case.query or case.case_id) for case in cases}
    return measure(cases, results), results
