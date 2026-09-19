from dataclasses import dataclass, field
from typing import Protocol

from acxes.config import Settings


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: tuple[dict, ...] = field(default_factory=tuple)


class LLMClient(Protocol):
    """Contrato mínimo e independiente del proveedor."""

    def complete(self, system: str, messages: list[LLMMessage]) -> LLMResponse: ...


class MockLLMClient:
    """Cliente determinista para CI. No realiza llamadas de red."""

    def __init__(self, canned: str = "respuesta simulada") -> None:
        self._canned = canned
        self.calls: list[tuple[str, list[LLMMessage]]] = []

    def complete(self, system: str, messages: list[LLMMessage]) -> LLMResponse:
        self.calls.append((system, list(messages)))
        return LLMResponse(text=self._canned)


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_client == "mock":
        return MockLLMClient()
    # El cliente real se implementa en la etapa 4, cuando se elija proveedor
    raise NotImplementedError("Cliente real pendiente de la etapa 4")
