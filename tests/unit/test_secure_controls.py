import pytest

from acxes.audit import InMemoryAuditSink, audit_event
from acxes.evaluation.metrics import EvaluationCase, measure
from acxes.orchestrator.turn import TurnResult
from acxes.output_guard.aggregation import (
    AggregationDenied,
    aggregate_salary,
    is_aggregate_request,
)


def test_audit_sink_registra_decision_sin_exponerla_al_modelo():
    sink = InMemoryAuditSink()
    audit_event(
        sink,
        user_id=None,
        query="consulta",
        decision={"decision": "deny"},
        policy_version="v1",
    )
    assert len(sink.events) == 1
    assert sink.events[0].decision["decision"] == "deny"


def test_agregacion_exige_cohorte_minima():
    with pytest.raises(AggregationDenied):
        aggregate_salary([1, 2])
    assert aggregate_salary([1, 2, 3])["average"] == 2
    assert is_aggregate_request("Necesito el reporte global de nómina")


def test_metricas_calculan_fuga_denegacion_y_citas():
    case = EvaluationCase(
        "t1", expected_doc_ids=frozenset({"doc-1"}), forbidden_tokens=frozenset({"CANARY"})
    )
    result = TurnResult("respuesta", (), ("chunk-1",), 2, 3, 0.1, 1)
    metrics = measure([case], {"t1": result}, {"t1": {"doc-1"}})
    assert metrics.leakage_rate == 0
    assert metrics.false_denial_rate == 0
    assert metrics.valid_citation_rate == 1
