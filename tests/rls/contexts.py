"""SecurityContext de las seis personas de prueba, tal como los construiría la API de borde
a partir de un token válido de Keycloak. Los datos salen de `oracle.PERSONAS` y del orden
de `acxes/db/seed.sql`."""

import os
from uuid import UUID

import psycopg
import pytest

from acxes.config import Settings, get_settings, postgres_dsn
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


def hybrid_settings() -> Settings:
    """Configuración en modo híbrido para las pruebas contra la base.

    Si `.env` ya está en modo híbrido se usa tal cual, con el modelo con el que se ingirió el
    corpus. Si no, se usa el embedder de prueba `hash`, que es con el que CI ingiere
    (.github/workflows/ci.yml). Exige que el corpus tenga vectores: en CI falla y en local se
    omite, con la instrucción para generarlos.
    """
    settings = get_settings()
    if settings.retrieval_mode != "hybrid":
        settings = settings.model_copy(
            # El umbral está calibrado para bge-m3 y no aplica al embedder de prueba
            update={
                "retrieval_mode": "hybrid",
                "embedding_backend": "hash",
                "embedding_min_similarity": None,
            }
        )
    try:
        with psycopg.connect(postgres_dsn(settings), autocommit=True) as conn:
            con_vector = conn.execute(
                "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
    except psycopg.errors.UndefinedColumn:
        # Base aplicada antes de acxes/db/vector.sql
        con_vector = 0
    if not con_vector:
        mensaje = (
            "El corpus no tiene embeddings. Ingiéralo con RETRIEVAL_MODE=hybrid "
            "(y EMBEDDING_BACKEND=hash sin el modelo): python -m acxes.db.apply"
        )
        if os.environ.get("CI"):
            pytest.fail(mensaje)
        pytest.skip(mensaje)
    return settings
