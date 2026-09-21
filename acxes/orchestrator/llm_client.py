import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from acxes.config import Settings


class LLMInfrastructureError(Exception):
    """Fallo del proveedor o de la red. El mensaje es genérico y nunca incluye la clave
    ni el cuerpo de la respuesta. En las corridas de evaluación se marca y se repite."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ToolSpec:
    """Definición de una herramienta que se ofrece al modelo. `parameters` es un esquema JSON."""

    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    # Se rellena si el proveedor entregó argumentos que no son JSON válido
    error: str | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str
    # Solo en mensajes del asistente que piden herramientas
    tool_calls: tuple[ToolCall, ...] = ()
    # Solo en mensajes con rol "tool"
    tool_call_id: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)


class LLMClient(Protocol):
    """Contrato mínimo e independiente del proveedor."""

    def complete(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: tuple[ToolSpec, ...] = (),
    ) -> LLMResponse: ...


class MockLLMClient:
    """Cliente determinista para CI. No realiza llamadas de red."""

    def __init__(self, canned: str = "respuesta simulada") -> None:
        self._canned = canned
        self.calls: list[tuple[str, list[LLMMessage]]] = []

    def complete(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: tuple[ToolSpec, ...] = (),
    ) -> LLMResponse:
        self.calls.append((system, list(messages)))
        return LLMResponse(text=self._canned)


_STOPWORDS = frozenset(
    [
        "cual",
        "cuales",
        "como",
        "donde",
        "quien",
        "quienes",
        "para",
        "pero",
        "porque",
        "sobre",
        "entre",
        "hacia",
        "desde",
        "hasta",
        "esta",
        "este",
        "esto",
        "estos",
        "estas",
        "puedes",
        "puede",
        "podria",
        "dime",
        "dame",
        "quiero",
        "necesito",
        "favor",
        "todos",
        "todas",
        "cada",
        "tiene",
        "tienen",
        "sido",
        "ser",
        "son",
        "con",
        "sin",
        "por",
        "que",
        "los",
        "las",
        "del",
        "una",
        "uno",
        "unos",
        "unas",
        "sus",
        "mis",
        "tus",
        "nos",
        "les",
    ]
)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


class NaiveMockLLMClient:
    """Simula, de forma determinista y sin red, a un modelo sin restricciones propias:
    convierte la petición del usuario en una búsqueda de palabras clave y comparte sin
    filtrar lo que la herramienta le devuelve.

    No es un modelo de lenguaje real. Es un doble de prueba que reproduce el punto ciego
    de autorización de B1 para poder probarla en CI sin red ni gasto en tokens. Con
    `LLM_CLIENT=real` el agente usa Groq sin tocar el resto del código.
    """

    _WORD = re.compile(r"[\wÁÉÍÓÚÑÜáéíóúñü]+")
    MIN_KEYWORDS = 3
    MAX_KEYWORDS = 8

    def __init__(self) -> None:
        self._counter = 0

    def complete(
        self,
        system: str,
        messages: list[LLMMessage],
        tools: tuple[ToolSpec, ...] = (),
    ) -> LLMResponse:
        last = messages[-1]

        if last.role == "tool":
            return LLMResponse(text=self._render(json.loads(last.content)))

        keywords = self._keywords(last.content)
        if len(keywords) < self.MIN_KEYWORDS:
            return LLMResponse(text="No encontré una consulta clara sobre documentos.")
        self._counter += 1
        call = ToolCall(
            id=f"call_{self._counter}",
            name="buscar_documentos",
            arguments={"keywords": keywords},
        )
        return LLMResponse(text="", tool_calls=(call,))

    def _keywords(self, text: str) -> list[str]:
        words = self._WORD.findall(text)
        # Los nombres propios (con mayúscula, salvo la primera palabra) van primero
        proper = [w for i, w in enumerate(words) if i > 0 and w[0].isupper() and len(w) > 2]
        common = [
            w
            for w in words
            if w not in proper and len(w) >= 4 and _strip_accents(w.lower()) not in _STOPWORDS
        ]
        ordered = list(dict.fromkeys(proper + common))
        return [w[:40] for w in ordered[: self.MAX_KEYWORDS]]

    @staticmethod
    def _render(data: dict) -> str:
        if "error" in data:
            return "No pude completar la consulta."
        resultados = data.get("resultados")
        if resultados is not None:
            if not resultados:
                return "No encontré información sobre eso."
            filas = " | ".join(
                f"[{r['chunk_id']}] {r['title']}: {r['content']}" for r in resultados
            )
            return f"Encontré lo siguiente: {filas}"
        if data.get("encontrado") is False:
            return "No encontré ese documento."
        if "chunks" in data:
            cuerpo = " ".join(c["content"] for c in data["chunks"])
            return f"Documento {data['title']}: {cuerpo}"
        return "No tengo información suficiente para responder."


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_client == "mock":
        return MockLLMClient()
    if settings.llm_provider.lower() != "groq":
        raise ValueError("LLM_CLIENT=real requiere LLM_PROVIDER=groq")
    from acxes.orchestrator.groq_client import GroqLLMClient

    return GroqLLMClient(settings)
