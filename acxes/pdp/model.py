"""Tipos del PDP: nivel de sensibilidad ordenado, predicado y decisión.

El predicado es una estructura de datos y no SQL. El servicio de recuperación lo traduce a
parámetros ligados y a variables de sesión (docs/VARIABLES_SESION.md).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Literal
from uuid import UUID


class Sensitivity(IntEnum):
    """Mismo orden que el enum `sensitivity_level` de PostgreSQL."""

    publico = 0
    interno = 1
    confidencial = 2
    restringido = 3


@dataclass(frozen=True)
class Predicate:
    allowed_depts: tuple[str, ...]
    max_sensitivity: Sensitivity
    owner_id: UUID
    acl_tags: tuple[str, ...]

    def allows(
        self, dept: str, sensitivity: str, owner_id: UUID | None, acl_tags: tuple[str, ...]
    ) -> bool:
        """Regla de visibilidad de documents/POLITICAS_ACCESO.md, la misma que aplica RLS."""
        level = Sensitivity[sensitivity]
        # 1. Dependencia permitida y nivel dentro del tope. Nunca restringido por esta vía
        if (
            dept in self.allowed_depts
            and level < Sensitivity.restringido
            and level <= self.max_sensitivity
        ):
            return True
        # 2. Propiedad hasta confidencial
        if owner_id is not None and owner_id == self.owner_id and level <= Sensitivity.confidencial:
            return True
        # 3. Restringido solo por intersección de etiquetas
        return level == Sensitivity.restringido and bool(set(acl_tags) & set(self.acl_tags))


@dataclass(frozen=True)
class Decision:
    decision: Literal["allow", "deny"]
    policy_version: str
    evaluated_at: datetime
    predicate: Predicate | None = None
    # Rol y dependencia tomados de la base. Solo para las variables de auditoría app.roles y
    # app.dept
    role: str | None = None
    dept: str | None = None
    # Claims del token que difieren de la base. Solo para la auditoría, no cambian la decisión
    claims_drift: tuple[str, ...] = ()
    # Código para la auditoría. Nunca se muestra al usuario (P14)
    reason: str = "ok"

    @property
    def allowed(self) -> bool:
        return self.decision == "allow" and self.predicate is not None
