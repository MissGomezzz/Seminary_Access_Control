import json
import re
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


class NaiveMockLLMClient:
    """Simula, de forma determinista y sin red, a un modelo sin restricciones
    propias: pide cualquier dato con solo reconocer la intención en el texto
    del usuario, y comparte sin filtrar lo que la herramienta le devuelve.

    Esto NO es un modelo de lenguaje real: es un doble de prueba que reproduce
    a propósito el punto ciego de autorización descrito en la sección 1 del
    Hito 1, para poder probar la arquitectura Unsecure (B1) de forma
    reproducible en CI, sin llamadas de red ni gasto en tokens. Cuando se
    quiera repetir el experimento contra un modelo real, basta con
    intercambiar este cliente por el que se implemente en la etapa 4
    (`LLM_CLIENT=real`) sin tocar el resto del agente.
    """

    _INTENTS: tuple[tuple[re.Pattern, str, str], ...] = (
        (re.compile(r"salari?o d[e|el]\s+([\wÁÉÍÓÚÑÜáéíóúñü ]+)", re.IGNORECASE),
         "consultar_salario", "nombre_empleado"),
        (re.compile(r"equipo (?:de|que dirige|que lidera)\s+([\wÁÉÍÓÚÑÜáéíóúñü ]+)", re.IGNORECASE),
         "consultar_equipo", "nombre_supervisor"),
        (re.compile(r"reporte\s+(?:global\s+)?de\s+n[oó]mina", re.IGNORECASE),
         "reporte_nomina_global", None),
    )

    def complete(self, system: str, messages: list[LLMMessage]) -> LLMResponse:
        last = messages[-1]

        if last.role == "tool":
            return LLMResponse(text=self._render(json.loads(last.content)))

        for pattern, tool_name, arg_name in self._INTENTS:
            match = pattern.search(last.content)
            if match:
                args = {arg_name: match.group(1).strip()} if arg_name else {}
                return LLMResponse(text="", tool_calls=({"name": tool_name, "arguments": args},))

        return LLMResponse(text="No encontré una consulta clara sobre nómina o equipos.")

    @staticmethod
    def _render(data: dict) -> str:
        if data.get("encontrado") is False:
            return "No encontré a esa persona en la base."
        if "salary" in data:
            return f"El salario de {data['full_name']} ({data['role']}) es ${data['salary']:,.0f}."
        if "miembros" in data:
            filas = ", ".join(
                f"{m['full_name']} (${m['salary']:,.0f})" for m in data["miembros"]
            )
            return f"El equipo {data['equipo']} está compuesto por: {filas}."
        if "empleados" in data:
            filas = ", ".join(
                f"{e['full_name']}: ${e['salary']:,.0f}" for e in data["empleados"]
            )
            return f"Reporte global de nómina: {filas}."
        return "No tengo información suficiente para responder."


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_client == "mock":
        return MockLLMClient()
    # El cliente real se implementa en la etapa 4, cuando se elija proveedor
    raise NotImplementedError("Cliente real pendiente de la etapa 4")
