"""Cliente de Groq detrás de `LLMClient`.

Groq expone una API compatible con OpenAI: POST `{base_url}/chat/completions` con
mensajes y definiciones de herramientas. Se usa `httpx` directamente para no depender
de un SDK y poder simular el transporte en las pruebas.
"""

import json
import time
from collections.abc import Callable

import httpx

from acxes.config import Settings
from acxes.orchestrator.llm_client import (
    LLMInfrastructureError,
    LLMMessage,
    LLMResponse,
    ToolCall,
    ToolSpec,
    Usage,
)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_WAIT_S = 30.0
_MAX_DETAIL_CHARS = 200
_ENDPOINT = "/chat/completions"


class GroqLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        api_key = settings.llm_api_key.get_secret_value()
        if not (settings.llm_base_url and api_key and settings.llm_model_agent):
            raise ValueError(
                "Configuración del modelo incompleta: defina LLM_BASE_URL, LLM_API_KEY "
                "y LLM_MODEL_AGENT en .env"
            )
        self._model = settings.llm_model_agent
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens
        self._max_retries = settings.llm_max_retries
        self._sleep = sleep
        self._api_key = api_key
        # La clave solo se desenvuelve aquí, para el encabezado
        self._client = httpx.Client(
            base_url=_normalize_base_url(settings.llm_base_url),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(settings.llm_timeout_s),
            transport=transport,
        )

    def complete(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: tuple[ToolSpec, ...] = (),
    ) -> LLMResponse:
        payload: dict = {
            "model": self._model,
            "messages": _to_wire(system, messages),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"
        return _parse(self._post(payload))

    def _post(self, payload: dict) -> dict:
        for attempt in range(self._max_retries + 1):
            last_attempt = attempt == self._max_retries
            try:
                response = self._client.post(_ENDPOINT, json=payload)
            except httpx.TransportError as exc:
                if last_attempt:
                    raise LLMInfrastructureError(
                        "No fue posible contactar al servicio del modelo"
                    ) from exc
                self._sleep(_backoff(attempt, None))
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise LLMInfrastructureError(
                        "El servicio del modelo devolvió una respuesta inválida"
                    ) from exc
            if response.status_code in _RETRYABLE_STATUS and not last_attempt:
                self._sleep(_backoff(attempt, response.headers.get("retry-after")))
                continue
            raise LLMInfrastructureError(
                f"El servicio del modelo respondió con estado {response.status_code}"
                f"{self._client_error_detail(response)}",
                status_code=response.status_code,
            )
        raise LLMInfrastructureError("No fue posible obtener respuesta del modelo")

    def _client_error_detail(self, response: httpx.Response) -> str:
        """Código y mensaje del error de Groq, solo para errores 4xx no reintentables.
        Distingue, por ejemplo, un modelo inexistente de una URL errónea. Nunca incluye el
        cuerpo completo ni la clave, y se trunca."""
        if not 400 <= response.status_code < 500 or response.status_code == 429:
            return ""
        try:
            error = response.json().get("error") or {}
            parts = [str(error[k]) for k in ("code", "message") if error.get(k)]
        except (ValueError, AttributeError, TypeError):
            return ""
        if not parts:
            return ""
        detail = " - ".join(parts).replace(self._api_key, "***")
        return f": {detail[:_MAX_DETAIL_CHARS]}"


def _normalize_base_url(url: str) -> str:
    """Tolera que LLM_BASE_URL incluya el endpoint completo o una barra final."""
    url = url.strip().rstrip("/").removesuffix(_ENDPOINT)
    return url.rstrip("/")


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), _MAX_WAIT_S)
        except ValueError:
            pass
    return min(2.0**attempt, _MAX_WAIT_S)


def _to_wire(system: str, messages: list[LLMMessage]) -> list[dict]:
    wire: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "tool":
            wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.tool_calls:
            wire.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ],
                }
            )
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire


def _parse(data: dict) -> LLMResponse:
    try:
        message = data["choices"][0]["message"]
        calls = tuple(_parse_call(c) for c in message.get("tool_calls") or [])
        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content") or "",
            tool_calls=calls,
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMInfrastructureError(
            "El servicio del modelo devolvió una respuesta inesperada"
        ) from exc


def _parse_call(raw: dict) -> ToolCall:
    function = raw["function"]
    try:
        arguments = json.loads(function.get("arguments") or "{}")
        if not isinstance(arguments, dict):
            raise TypeError("los argumentos no son un objeto")
    except (ValueError, TypeError):
        return ToolCall(
            id=raw["id"],
            name=function["name"],
            error="Los argumentos de la herramienta no son un objeto JSON válido",
        )
    return ToolCall(id=raw["id"], name=function["name"], arguments=arguments)
