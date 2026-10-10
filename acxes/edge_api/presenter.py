"""Convierte el resultado de un turno de S en el JSON que consume el front.

Es solo presentación. No decide ni filtra nada: lo que el modelo vio ya lo decidieron el PDP y
RLS. Tampoco expone el motivo de una denegación (P14), los claims ni los resultados de las
herramientas. Lo que el modelo escribió como argumentos de herramienta se recorta antes de
mostrarlo, porque es texto que el modelo pudo haber tomado de un documento.
"""

import re
from collections.abc import Sequence

from acxes.orchestrator.llm_client import ToolCall
from acxes.orchestrator.turn import TurnResult
from acxes.pdp.model import Decision
from acxes.retrieval.types import ChunkMeta

# Marcas con las que el Tool Gateway delimita los fragmentos como datos. No son para el usuario
_DATA_MARKS = re.compile(r"<<<DATOS[^>\n]*>>>|<<<FIN DATOS>>>")
_BLANK_LINES = re.compile(r"\n{3,}")

_MAX_ARGS = 8
_MAX_ARG_CHARS = 80


def clean_text(text: str) -> str:
    """Quita las marcas de delimitación de datos y los saltos de línea sobrantes."""
    return _BLANK_LINES.sub("\n\n", _DATA_MARKS.sub("", text)).strip()


def _short(value: object) -> str:
    text = str(value)
    return text if len(text) <= _MAX_ARG_CHARS else text[: _MAX_ARG_CHARS - 1] + "…"


def _safe_args(call: ToolCall) -> dict:
    out: dict = {}
    for name, value in list(call.arguments.items())[:_MAX_ARGS]:
        if isinstance(value, list | tuple):
            out[_short(name)] = [_short(v) for v in value[:_MAX_ARGS]]
        else:
            out[_short(name)] = _short(value)
    return out


def group_sources(metas: Sequence[ChunkMeta]) -> list[dict]:
    """Una fuente por documento, en el orden en que aparecieron, con sus fragmentos."""
    sources: dict[str, dict] = {}
    for m in metas:
        entry = sources.setdefault(
            m.doc_id,
            {
                "doc_id": m.doc_id,
                "title": m.title,
                "dept": m.dept,
                "sensitivity": m.sensitivity,
                "acl_tags": list(m.acl_tags),
                "chunk_ids": [],
            },
        )
        entry["chunk_ids"].append(m.chunk_id)
    return list(sources.values())


def predicate_view(decision: Decision) -> dict | None:
    p = decision.predicate
    if not decision.allowed or p is None:
        return None
    return {
        "allowed_depts": list(p.allowed_depts),
        "max_sensitivity": p.max_sensitivity.name,
        "owner_id": str(p.owner_id),
        "acl_tags": list(p.acl_tags),
    }


def turn_status(turn: TurnResult, decision: Decision) -> str:
    """answered | no_results | denied | truncated. El front lo usa para el estilo del mensaje."""
    if not decision.allowed:
        return "denied"
    if turn.truncated:
        return "truncated"
    return "answered" if turn.chunk_ids else "no_results"


def present_turn(turn: TurnResult, decision: Decision, sources: Sequence[ChunkMeta]) -> dict:
    return {
        "answer": clean_text(turn.text),
        "status": turn_status(turn, decision),
        "citations": group_sources(sources),
        "gateway": {
            "engine": "secure",
            "policy_version": decision.policy_version,
            "decision": decision.decision,
            "predicate": predicate_view(decision),
            "tool_calls": [{"name": _short(c.name), "args": _safe_args(c)} for c in turn.tool_calls],
            "chunks": len(turn.chunk_ids),
            # La guardia de salida es la etapa 5. Hasta que exista no se afirma que se aplicó
            "output_guard": "pending",
            "iterations": turn.iterations,
            "prompt_tokens": turn.prompt_tokens,
            "completion_tokens": turn.completion_tokens,
            "latency_s": round(turn.latency_s, 3),
            "truncated": turn.truncated,
        },
    }
