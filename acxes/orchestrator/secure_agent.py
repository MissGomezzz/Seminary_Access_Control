"""Orquestador del agente S (etapa 4).

El modelo solo elige herramientas y argumentos de negocio. El SecurityContext lo inyecta este
código en el Tool Gateway y nunca aparece en el prompt ni en los mensajes. El orquestador no
tiene credenciales de base de datos: su único camino a los datos es el gateway.

El ciclo reproduce el de B1 (mismo catálogo, mismo `TurnResult`, 4 iteraciones y el mismo
presupuesto de tokens por turno) para que la comparación cambie solo la autorización.
"""

import time
from typing import Protocol

from acxes.orchestrator.history import HistoryKey, InMemoryHistoryStore
from acxes.orchestrator.llm_client import LLMClient, LLMMessage, ToolCall
from acxes.orchestrator.prompts import SYSTEM_PROMPT
from acxes.orchestrator.tool_catalog import tool_specs
from acxes.orchestrator.turn import TRUNCATED_MESSAGE, TurnResult, to_json
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
        mensajes.append(LLMMessage(role="user", content=message))

        llamadas: list[ToolCall] = []
        chunk_ids: list[str] = []
        prompt_tokens = completion_tokens = 0
        texto = TRUNCATED_MESSAGE
        truncado = True
        iteraciones = 0

        while iteraciones < self._max_iterations:
            respuesta = self._llm.complete(SYSTEM_PROMPT, mensajes, tool_specs())
            iteraciones += 1
            prompt_tokens += respuesta.usage.prompt_tokens
            completion_tokens += respuesta.usage.completion_tokens

            if not respuesta.tool_calls:
                texto = respuesta.text
                truncado = False
                break
            # P13: presupuesto de tokens del turno, igual que en B1
            if prompt_tokens + completion_tokens >= self._max_turn_tokens:
                break

            mensajes.append(
                LLMMessage(
                    role="assistant", content=respuesta.text, tool_calls=respuesta.tool_calls
                )
            )
            for llamada in respuesta.tool_calls:
                llamadas.append(llamada)
                resultado = self._ejecutar(ctx, llamada)
                chunk_ids.extend(resultado.chunk_ids)
                mensajes.append(
                    LLMMessage(
                        role="tool", content=to_json(resultado.payload), tool_call_id=llamada.id
                    )
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
        )

    def _ejecutar(self, ctx: SecurityContext, llamada: ToolCall) -> GatewayResult:
        if llamada.error:
            return GatewayResult({"error": "argumentos inválidos"}, reason="invalid_json")
        return self._gateway.execute(ctx, llamada.name, llamada.arguments)
