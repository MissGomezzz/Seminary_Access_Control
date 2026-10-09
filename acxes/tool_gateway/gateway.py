"""PEP de herramientas: valida llamadas, consulta el PDP y recupera con el predicado."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from acxes.orchestrator.llm_client import ToolCall
from acxes.orchestrator.tool_catalog import TOOL_MODELS
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.retrieval.secure import RetrievalDenied, RetrievalError, SecureRetrievalService
from acxes.security_context import SecurityContext

_INVALID = "argumentos inválidos"
_DENIED = "No encontré información sobre eso con tu nivel de acceso actual."


class ToolGateway:
    """Ejecuta únicamente las herramientas del catálogo cerrado."""

    def __init__(self, pdp: PolicyDecisionPoint, retrieval: SecureRetrievalService) -> None:
        self._pdp = pdp
        self._retrieval = retrieval

    def execute(self, ctx: SecurityContext, call: ToolCall) -> dict[str, Any]:
        if call.error:
            return {"error": _INVALID}
        model = TOOL_MODELS.get(call.name)
        if model is None:
            return {"error": f"herramienta desconocida: {call.name}"}
        try:
            args = model.model_validate(call.arguments)
        except ValidationError:
            return {"error": _INVALID}

        action = "search" if call.name == "buscar_documentos" else "read"
        decision = self._pdp.evaluate(ctx, action, "documentos")
        if not decision.allowed:
            return {"error": _DENIED}
        try:
            if call.name == "buscar_documentos":
                hits = self._retrieval.search(ctx, decision, list(args.keywords))
                return {"resultados": [_hit_dict(hit) for hit in hits]}
            record = self._retrieval.read_document(ctx, decision, args.doc_id)
            if record is None:
                return {"encontrado": False}
            return {
                "doc_id": record.doc_id,
                "title": record.title,
                "chunks": [{"chunk_id": h.chunk_id, "content": h.content} for h in record.chunks],
            }
        except (RetrievalDenied, RetrievalError):
            return {"error": _DENIED}

    def invoke(self, ctx: SecurityContext, call: ToolCall) -> dict[str, Any]:
        """Alias explícito para consumidores que nombran la operación «invocar»."""
        return self.execute(ctx, call)


def _hit_dict(hit: object) -> dict[str, str]:
    return {
        "chunk_id": hit.chunk_id,
        "doc_id": hit.doc_id,
        "title": hit.title,
        "content": hit.content,
    }
