"""Orquestador Secure: identidad fuera de banda y herramientas mediadas por el gateway."""

import json
import time
from decimal import Decimal

from acxes.orchestrator.llm_client import LLMClient, LLMInfrastructureError, LLMMessage, ToolCall
from acxes.orchestrator.tool_catalog import tool_specs
from acxes.orchestrator.turn import TurnResult
from acxes.output_guard import guard_output
from acxes.output_guard.aggregation import is_aggregate_request
from acxes.security_context import SecurityContext
from acxes.tool_gateway import ToolGateway

TRUNCATED_MESSAGE = "No fue posible completar la consulta."
_SYSTEM = (
    "Eres el asistente institucional. Usa únicamente las herramientas disponibles. "
    "Responde solo con información recuperada y cita cada fragmento usando su chunk_id."
)


class SecureAgent:
    def __init__(self, llm: LLMClient, gateway: ToolGateway, max_iterations: int = 4) -> None:
        self._llm = llm
        self._gateway = gateway
        self._max_iterations = max_iterations
        self._historial: list[LLMMessage] = []
        self._session_key: tuple[object, str] | None = None

    def responder(self, ctx: SecurityContext, consulta: str) -> TurnResult:
        key = (ctx.user_id, ctx.policy_version)
        if self._session_key != key:
            self._historial.clear()
            self._session_key = key
        base = len(self._historial)
        try:
            return self._turno(ctx, consulta)
        except LLMInfrastructureError:
            del self._historial[base:]
            raise

    def _turno(self, ctx: SecurityContext, consulta: str) -> TurnResult:
        started = time.perf_counter()
        if is_aggregate_request(consulta):
            return TurnResult(
                text="No puedo entregar agregados de nómina sin una cohorte autorizada de al menos 3 personas.",
                tool_calls=(),
                chunk_ids=(),
                prompt_tokens=0,
                completion_tokens=0,
                latency_s=time.perf_counter() - started,
                iterations=0,
                truncated=False,
            )
        self._historial.append(LLMMessage(role="user", content=consulta))
        calls: list[ToolCall] = []
        chunk_ids: list[str] = []
        prompt_tokens = completion_tokens = 0
        text, truncated, iterations = TRUNCATED_MESSAGE, True, 0
        while iterations < self._max_iterations:
            response = self._llm.complete(_SYSTEM, self._historial, tool_specs())
            iterations += 1
            prompt_tokens += response.usage.prompt_tokens
            completion_tokens += response.usage.completion_tokens
            if not response.tool_calls:
                guarded = guard_output(response.text, tuple(dict.fromkeys(chunk_ids)))
                text, truncated = guarded.text, False
                self._historial.append(LLMMessage(role="assistant", content=text))
                break
            self._historial.append(
                LLMMessage(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            for call in response.tool_calls:
                calls.append(call)
                result = self._gateway.execute(ctx, call)
                chunk_ids.extend(_chunk_ids(result))
                self._historial.append(
                    LLMMessage(role="tool", content=_to_json(result), tool_call_id=call.id)
                )
        if truncated:
            self._historial.append(LLMMessage(role="assistant", content=text))
        return TurnResult(
            text=text,
            tool_calls=tuple(calls),
            chunk_ids=tuple(dict.fromkeys(chunk_ids)),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_s=time.perf_counter() - started,
            iterations=iterations,
            truncated=truncated,
        )


def _chunk_ids(result: dict) -> list[str]:
    ids = [r["chunk_id"] for r in result.get("resultados", [])]
    ids.extend(c["chunk_id"] for c in result.get("chunks", []))
    return ids


def _to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=_json_default)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {value.__class__.__name__} no es serializable")


SecureOrchestrator = SecureAgent
