"""Servicio de la API de borde: une la identidad ya validada con el agente S.

Sigue documents/CONTRATO_ETAPA2.md. Recibe los claims de un token que otra capa ya validó,
construye el `SecurityContext` con la versión de política del PDP y llama al orquestador. El
JWT no pasa de aquí, y la identidad nunca llega al modelo.

El perfil que se muestra (rol, dependencias, nivel y etiquetas) sale de la decisión del PDP, que
lee la base, y no de los claims. Un claim desactualizado no puede mostrar permisos que ya no
existen.

Fallas. Una denegación del PDP por falla de infraestructura (base caída, política ilegible,
tiempo agotado) se informa como 503 y no como falta de permisos: el usuario no pierde acceso
porque la base esté caída. Sigue siendo fail-closed, porque no se entrega nada.
"""

import logging
from collections.abc import Callable

from acxes.edge_api.errors import AccessDenied, BackendUnavailable, InvalidIdentity
from acxes.edge_api.presenter import predicate_view, present_turn
from acxes.orchestrator.llm_client import LLMInfrastructureError
from acxes.pdp.model import Decision
from acxes.retrieval.secure import RetrievalDenied, RetrievalError
from acxes.security_context import SecurityContext
from acxes.tool_gateway.gateway import RESOURCE

log = logging.getLogger("acxes.edge")

# Motivos de `Decision.reason` que indican una falla del sistema y no una falta de permisos
INFRA_REASONS = frozenset({"error", "timeout", "no_policy", "policy_version", "subject_error"})


class ChatService:
    def __init__(
        self,
        agent,
        pdp,
        retrieval,
        display_name: Callable[[str], str | None] | None = None,
    ) -> None:
        self._agent = agent
        self._pdp = pdp
        self._retrieval = retrieval
        # El token no lleva nombre (sin PII). Solo el modo dev lo conoce, por sus usuarios de prueba
        self._display_name = display_name or (lambda _user_id: None)

    @property
    def policy_version(self) -> str | None:
        return self._pdp.policy_version

    def security_context(self, claims: dict) -> SecurityContext:
        version = self._pdp.policy_version
        if version is None:  # sin política válida se deniega todo
            log.error("edge: el PDP no tiene política válida")
            raise BackendUnavailable("no_policy")
        try:
            return SecurityContext.from_claims(claims, policy_version=version)
        except ValueError as exc:
            log.warning("edge: claims inválidos para el SecurityContext: %s", type(exc).__name__)
            raise InvalidIdentity from exc

    def _authorize(self, ctx: SecurityContext) -> Decision:
        decision = self._pdp.evaluate(ctx, "search", RESOURCE)
        if not decision.allowed and decision.reason in INFRA_REASONS:
            log.error("edge: el PDP no pudo decidir (%s)", decision.reason)
            raise BackendUnavailable(decision.reason)
        return decision

    def profile(self, claims: dict) -> dict:
        ctx = self.security_context(claims)
        decision = self._authorize(ctx)
        if not decision.allowed:
            log.warning("edge: acceso denegado a %s (%s)", ctx.user_id, decision.reason)
            raise AccessDenied
        view = predicate_view(decision)
        return {
            "user_id": str(ctx.user_id),
            "full_name": self._display_name(str(ctx.user_id)),
            "roles": [decision.role],
            "dept": decision.dept,
            "clearance": view["max_sensitivity"],
            "allowed_depts": view["allowed_depts"],
            "acl_tags": view["acl_tags"],
            "policy_version": decision.policy_version,
        }

    def chat(self, claims: dict, message: str) -> dict:
        ctx = self.security_context(claims)
        try:
            turn = self._agent.respond(ctx, message)
        except LLMInfrastructureError as exc:
            log.error("edge: falló el proveedor del modelo (%s)", exc.status_code)
            raise BackendUnavailable("llm") from exc
        decision = self._authorize(ctx)
        sources = []
        if decision.allowed and turn.chunk_ids:
            try:
                sources = self._retrieval.describe_chunks(ctx, decision, turn.chunk_ids)
            except (RetrievalDenied, RetrievalError):
                log.warning("edge: no se pudieron describir las fuentes del turno")
        return present_turn(turn, decision, sources)
