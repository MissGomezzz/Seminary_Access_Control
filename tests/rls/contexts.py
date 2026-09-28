"""SecurityContext de las seis personas de prueba, tal como los construiría la API de borde
a partir de un token válido de Keycloak. Los datos salen de `oracle.PERSONAS` y del orden
de `acxes/db/seed.sql`."""

from uuid import UUID

from acxes.config import get_settings
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.pdp.subject_store import PostgresSubjectStore
from acxes.security_context import SecurityContext
from tests.rls.oracle import PERSONAS

_SEED_ORDER = ("Sofía", "Belén", "Ángela", "Laura", "Carlos", "Diego")
_IDS = {
    name: UUID(f"00000000-0000-4000-a000-00000000000{i}") for i, name in enumerate(_SEED_ORDER, 1)
}
# Claim clearance que emite el realm según el rol (documents/MATRIZ_ACCESO.md)
_CLEARANCE = {"empleado": "interno", "supervisor": "confidencial", "administrador": "confidencial"}


def security_context(nombre: str, pdp: PolicyDecisionPoint) -> SecurityContext:
    person = PERSONAS[nombre]
    return SecurityContext(
        user_id=_IDS[nombre],
        roles=(person.role, "default-roles-acxes"),
        dept=person.dept,
        clearance=_CLEARANCE[person.role],
        acl_tags=person.tags,
        session_id=f"sesion-{nombre}",
        policy_version=pdp.policy_version,
    )


def database_pdp() -> PolicyDecisionPoint:
    """PDP con el almacén de atributos real, conectado como acxes_pdp."""
    return PolicyDecisionPoint(PostgresSubjectStore(get_settings()))
