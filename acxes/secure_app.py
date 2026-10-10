"""Punto de composición de S: arma el agente con sus componentes reales.

Aquí, y no en el orquestador, se crean las piezas con acceso a la base (el almacén de
atributos del PDP y el servicio de recuperación). El orquestador solo recibe el gateway.
La API de borde (etapa 2) crea una instancia por proceso y llama a
`agent.respond(security_context, mensaje)` en cada petición.
"""

from dataclasses import dataclass

from acxes.config import Settings, get_settings
from acxes.orchestrator.history import InMemoryHistoryStore
from acxes.orchestrator.llm_client import LLMClient, NaiveMockLLMClient, build_llm_client
from acxes.orchestrator.secure_agent import SecureAgent
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.pdp.subject_store import PostgresSubjectStore
from acxes.retrieval.secure import SecureRetrievalService
from acxes.tool_gateway.gateway import ToolGateway


def build_gateway(settings: Settings) -> ToolGateway:
    pdp = PolicyDecisionPoint(PostgresSubjectStore(settings))
    return ToolGateway(pdp, SecureRetrievalService(settings))


def build_agent_llm(settings: Settings) -> LLMClient:
    """Con `mock` se usa el mismo doble determinista que B1 en CI. Con `real`, Groq."""
    if settings.llm_client == "mock":
        return NaiveMockLLMClient()
    return build_llm_client(settings)


@dataclass(frozen=True)
class SecureStack:
    """Las piezas de S que la API de borde necesita, una instancia por proceso.

    El PDP es el mismo que usa el gateway. El servicio de recuperación sigue siendo el único
    componente con credencial de aplicación: la API de borde solo le pide los metadatos de las
    fuentes citadas, con el mismo predicado y las mismas variables de sesión.
    """

    agent: SecureAgent
    pdp: PolicyDecisionPoint
    retrieval: SecureRetrievalService


def build_secure_stack(settings: Settings | None = None) -> SecureStack:
    settings = settings or get_settings()
    pdp = PolicyDecisionPoint(PostgresSubjectStore(settings))
    retrieval = SecureRetrievalService(settings)
    agent = SecureAgent(
        build_agent_llm(settings),
        ToolGateway(pdp, retrieval),
        InMemoryHistoryStore(),
        max_iterations=settings.agent_max_iterations,
        max_turn_tokens=settings.agent_max_turn_tokens,
    )
    return SecureStack(agent, pdp, retrieval)


def build_secure_agent(settings: Settings | None = None) -> SecureAgent:
    return build_secure_stack(settings).agent
