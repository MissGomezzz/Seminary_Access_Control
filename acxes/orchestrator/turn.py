import json
from dataclasses import dataclass
from decimal import Decimal

from acxes.orchestrator.llm_client import ToolCall

# Respuesta cuando el turno se corta por el tope de iteraciones o de tokens (P13). Común a
# B1 y S para que la comparación no dependa del texto
TRUNCATED_MESSAGE = "No fue posible completar la consulta."


@dataclass(frozen=True)
class TurnResult:
    """Resultado de un turno, común a B1, B2 y S para medir con las mismas métricas.

    `chunk_ids` son los fragmentos entregados al modelo en el turno. La fuga se mide
    buscando tokens canario en `text` y en el contenido de esos fragmentos.
    """

    text: str
    tool_calls: tuple[ToolCall, ...]
    chunk_ids: tuple[str, ...]
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    iterations: int
    # Verdadero si se agotó el tope de iteraciones sin respuesta final
    truncated: bool = False


def to_json(data: dict) -> str:
    """Serializa un resultado de herramienta para el mensaje con rol `tool`."""

    def _default(o):
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

    return json.dumps(data, ensure_ascii=False, default=_default)
