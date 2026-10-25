"""Orquestador del agente S (etapa 4).

El modelo solo elige herramientas y argumentos de negocio. El SecurityContext lo inyecta este
código en el Tool Gateway y nunca aparece en el prompt ni en los mensajes. El orquestador no
tiene credenciales de base de datos: su único camino a los datos es el gateway.

El ciclo reproduce el de B1 (mismo catálogo, mismo `TurnResult`, 4 iteraciones y el mismo
presupuesto de tokens por turno) para que la comparación cambie solo la autorización.
"""

import time
from typing import Protocol

from acxes.dev_audit import dev_audit, preview
from acxes.orchestrator.history import HistoryKey, InMemoryHistoryStore
from acxes.orchestrator.llm_client import LLMClient, LLMMessage, ToolCall
from acxes.orchestrator.prompts import SYSTEM_PROMPT
from acxes.orchestrator.tool_catalog import tool_specs
from acxes.orchestrator.turn import TRUNCATED_MESSAGE, ToolDecision, TurnResult, to_json
from acxes.security_context import SecurityContext
from acxes.tool_gateway.gateway import GatewayResult

# Mismo texto para cualquier denegación. La guardia de salida de la etapa 5 lo aplicará también
DENIAL_MESSAGE = "No encontré información disponible para tu perfil sobre esa consulta."


class Gateway(Protocol):
    def authorization_fingerprint(self, ctx: SecurityContext) -> str | None: ...
    def execute(self, ctx: SecurityContext, name: str, arguments: dict) -> GatewayResult: ...


class SecureAgent:
    def __init__(
        self,
        llm: LLMClient,
        gateway: Gateway,
        history: InMemoryHistoryStore,
        max_iterations: int = 4,
        max_turn_tokens: int = 16000,
    ) -> None:
        self._llm = llm
        self._gateway = gateway
        self._history = history
        self._max_iterations = max_iterations
        self._max_turn_tokens = max_turn_tokens

    def respond(self, ctx: SecurityContext, message: str) -> TurnResult:
        inicio = time.perf_counter()
        fingerprint = self._gateway.authorization_fingerprint(ctx)
        if fingerprint is None:
            # Sin autorización vigente no se llama al modelo
            dev_audit("agent: huella None (PDP denegó) -> DENIAL_MESSAGE sin llamar al modelo")
            return TurnResult(
                text=DENIAL_MESSAGE,
                tool_calls=(),
                chunk_ids=(),
                prompt_tokens=0,
                completion_tokens=0,
                latency_s=time.perf_counter() - inicio,
                iterations=0,
            )
        key = HistoryKey(ctx.user_id, ctx.session_id, ctx.policy_version, fingerprint)
        # Los mensajes del turno viven aquí. Al historial solo pasa el cierre del turno
        mensajes = self._history.load(key)
        dev_audit(
            "agent: turno nuevo session=%s historial=%d mensajes previos=%s",
            ctx.session_id, len(mensajes),
            [preview(m.content, 60) for m in mensajes if m.role == "assistant"],
        )
        mensajes.append(LLMMessage(role="user", content=message))

        llamadas: list[ToolCall] = []
        chunk_ids: list[str] = []
        prompt_tokens = completion_tokens = 0
        texto = TRUNCATED_MESSAGE
        truncado = True
        iteraciones = 0
        decisiones: list[ToolDecision] = []
        aggregate = False

        while iteraciones < self._max_iterations:
            respuesta = self._llm.complete(
                SYSTEM_PROMPT, mensajes, tool_specs(include_aggregation=True)
            )
            iteraciones += 1
            prompt_tokens += respuesta.usage.prompt_tokens
            completion_tokens += respuesta.usage.completion_tokens
            dev_audit(
                "agent: iter=%d tokens acumulados=%d/%d tool_calls=%s texto=%r",
                iteraciones, prompt_tokens + completion_tokens, self._max_turn_tokens,
                [(c.name, c.arguments, c.error) for c in respuesta.tool_calls],
                preview(respuesta.text),
            )

            if not respuesta.tool_calls:
                texto = respuesta.text
                truncado = False
                break
            # P13: presupuesto de tokens del turno, igual que en B1
            if prompt_tokens + completion_tokens >= self._max_turn_tokens:
                dev_audit("agent: CORTE por presupuesto de tokens -> TRUNCATED_MESSAGE")
                break

            mensajes.append(
                LLMMessage(
                    role="assistant", content=respuesta.text, tool_calls=respuesta.tool_calls
                )
            )
            for llamada in respuesta.tool_calls:
                llamadas.append(llamada)
                resultado = self._ejecutar(ctx, llamada)
                aggregate = aggregate or resultado.aggregate
                dev_audit(
                    "agent: herramienta %s -> reason=%s chunks=%d payload_keys=%s",
                    llamada.name, resultado.reason, len(resultado.chunk_ids),
                    sorted(resultado.payload),
                )
                decisiones.append(
                    ToolDecision(llamada.name, resultado.reason, resultado.reason == "ok")
                )
                chunk_ids.extend(resultado.chunk_ids)
                mensajes.append(
                    LLMMessage(
                        role="tool", content=to_json(resultado.payload), tool_call_id=llamada.id
                    )
                )

        if truncado:
            dev_audit("agent: turno TRUNCADO tras %d iteraciones", iteraciones)
        dev_audit(
            "agent: fin del turno chunks=%d aggregate=%s texto=%r",
            len(dict.fromkeys(chunk_ids)), aggregate, preview(texto),
        )
        self._history.append_turn(key, message, texto)
        return TurnResult(
            text=texto,
            tool_calls=tuple(llamadas),
            chunk_ids=tuple(dict.fromkeys(chunk_ids)),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_s=time.perf_counter() - inicio,
            iterations=iteraciones,
            truncated=truncado,
            tool_decisions=tuple(decisiones),
            aggregate=aggregate,
        )

    def _ejecutar(self, ctx: SecurityContext, llamada: ToolCall) -> GatewayResult:
        if llamada.error:
            return GatewayResult({"error": "argumentos inválidos"}, reason="invalid_json")
        return self._gateway.execute(ctx, llamada.name, llamada.arguments)
