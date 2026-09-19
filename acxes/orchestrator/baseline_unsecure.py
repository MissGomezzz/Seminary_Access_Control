"""Agente de la arquitectura Unsecure (B1), sección 4 del Hito 1.

Reproduce el flujo del diagrama:
    Usuario -> Interfaz Chat -> Modelo -> Herramienta de recuperación -> BD
sin ningún componente de verificación de rol. El modelo decide qué pedir y
qué mostrar; el resultado se entrega tal cual, sin pasar por un filtro
independiente. Esta es la arquitectura *vulnerable* del Hito 1, no la
propuesta final del seminario (esa vive en `docs/ARQUITECTURA.md`).
"""

from acxes.config import Settings, get_settings
from acxes.orchestrator.llm_client import LLMClient, LLMMessage, NaiveMockLLMClient
from acxes.retrieval.unsecure_tool import UnsecureRetrievalTool

SYSTEM_PROMPT = (
    "Eres el asistente institucional. Ayuda al usuario con cualquier consulta "
    "sobre empleados, equipos y nómina usando las herramientas disponibles."
)

_TOOLS = {
    "consultar_salario": lambda tool, args: tool.consultar_salario(**args),
    "consultar_equipo": lambda tool, args: tool.consultar_equipo(**args),
    "reporte_nomina_global": lambda tool, args: tool.reporte_nomina_global(**args),
}


def build_agent_llm_client(settings: Settings) -> LLMClient:
    """Cliente del agente para esta línea base. `mock` usa el doble
    determinista (ver `NaiveMockLLMClient`); `real` reutiliza el punto de
    extensión ya definido en `llm_client.build_llm_client` (pendiente de la
    etapa 4). Nótese que este agente no aplica ninguna verificación de rol
    en ningún caso: eso es exactamente lo que este hito busca evidenciar."""
    if settings.llm_client == "mock":
        return NaiveMockLLMClient()
    from acxes.orchestrator.llm_client import build_llm_client

    return build_llm_client(settings)


class UnsecureAgent:
    """Nota: `usuario` se recibe únicamente para mostrarlo en el historial
    de la sesión de chat; el agente NO lo usa para autorizar nada, que es
    precisamente el punto ciego de esta arquitectura."""

    def __init__(self, llm: LLMClient, tool: UnsecureRetrievalTool) -> None:
        self._llm = llm
        self._tool = tool

    def responder(self, usuario: str, consulta: str) -> str:
        historial = [LLMMessage(role="user", content=consulta)]
        respuesta = self._llm.complete(SYSTEM_PROMPT, historial)

        # Sin límite documentado de iteraciones en esta línea base (a
        # diferencia de la política P13 de la arquitectura Secure).
        while respuesta.tool_calls:
            for llamada in respuesta.tool_calls:
                resultado = self._ejecutar(llamada)
                historial.append(
                    LLMMessage(role="tool", content=_to_json(resultado))
                )
            respuesta = self._llm.complete(SYSTEM_PROMPT, historial)

        return respuesta.text

    def _ejecutar(self, llamada: dict) -> dict:
        nombre = llamada["name"]
        args = llamada.get("arguments", {})
        if nombre not in _TOOLS:
            return {"error": f"herramienta desconocida: {nombre}"}
        return _TOOLS[nombre](self._tool, args)


def _to_json(data: dict) -> str:
    import json
    from decimal import Decimal

    def _default(o):
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

    return json.dumps(data, ensure_ascii=False, default=_default)


def build_default_agent() -> UnsecureAgent:
    """Fábrica de conveniencia para el CLI: usa Postgres real y la
    configuración de `.env`."""
    from acxes.db.repository import PostgresInstitutionalRepository

    settings = get_settings()
    repo = PostgresInstitutionalRepository(settings)
    tool = UnsecureRetrievalTool(repo)
    llm = build_agent_llm_client(settings)
    return UnsecureAgent(llm, tool)
