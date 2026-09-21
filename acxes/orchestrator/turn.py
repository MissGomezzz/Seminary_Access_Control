from dataclasses import dataclass

from acxes.orchestrator.llm_client import ToolCall


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
