"""Contrato del SecurityContext, punto de unión entre la API de borde (etapa 2) y el resto de S.

La API de borde valida el JWT (firma RS256 contra el JWKS, `iss`, `aud`, `exp`, `nbf`, `azp`
y rechazo de `alg: none`) y solo entonces construye el contexto:

    ctx = SecurityContext.from_claims(claims_validados, policy_version=pdp.policy_version)

A partir de ahí el sistema trabaja con este objeto inmutable y nunca con el JWT. El
orquestador lo inyecta en el Tool Gateway y el modelo no lo ve ni lo redacta.

El contexto transporta la identidad tal como la afirma el token. No decide nada: las reglas
P7, P8 y P9 (nivel por rol, un único rol reconocido y dependencia válida) las aplica el PDP.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SecurityContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    # Roles del token sin filtrar. El PDP descarta los ajenos al sistema (P8)
    roles: tuple[str, ...]
    dept: str
    # Claim del token. Solo sirve para verificar que coincide con el nivel del rol (P7)
    clearance: str
    acl_tags: tuple[str, ...] = ()
    session_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any], policy_version: str) -> "SecurityContext":
        """Construye el contexto a partir de claims ya validados por la API de borde.

        `session_id` se toma del claim del mismo nombre o, si falta, de `sid`, que es el que
        emite Keycloak. Keycloak omite un atributo multivaluado vacío, por eso `acl_tags`
        ausente equivale a ninguna etiqueta. Un claim con tipo inesperado lanza ValueError.
        """
        realm_access = claims.get("realm_access") or {}
        if not isinstance(realm_access, Mapping):
            raise ValueError("realm_access debe ser un objeto")  # noqa: TRY004
        roles = _str_list(realm_access.get("roles", []), "realm_access.roles")
        acl_tags = _str_list(claims.get("acl_tags", []), "acl_tags")
        session_id = claims.get("session_id") or claims.get("sid")
        for name, value in (
            ("sub", claims.get("sub")),
            ("dept", claims.get("dept")),
            ("clearance", claims.get("clearance")),
            ("session_id", session_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"claim ausente o inválido: {name}")
        return cls(
            user_id=UUID(claims["sub"]),
            roles=tuple(roles),
            dept=claims["dept"],
            clearance=claims["clearance"],
            acl_tags=tuple(acl_tags),
            session_id=session_id,
            policy_version=policy_version,
        )


def _str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{name} debe ser una lista de cadenas")
    return list(value)
