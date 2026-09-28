"""PDP propio con reglas YAML versionadas (etapa 3).

Recibe el SecurityContext, la acción y el recurso, y devuelve una decisión con un predicado
estructurado. La base es la fuente de verdad para autorizar: del contexto solo se usa
`user_id`, y el rol, la dependencia y las etiquetas se leen del almacén de atributos en cada
evaluación. Los claims del token que difieran de la base se ignoran al decidir y se anotan en
`Decision.claims_drift` para la auditoría.

Deniega por defecto: ante política ausente o inválida, versión distinta, usuario
inexistente, fallo del almacén, rol o dependencia inválidos en la base, acción no permitida,
cualquier excepción o tiempo agotado (P7, P8, P9, P11 y P14). El motivo queda en
`Decision.reason` solo para auditoría.

El almacén aplica su propio tiempo máximo a la consulta. Además, el tiempo total de la
evaluación se comprueba al terminar.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from acxes.pdp.model import Decision, Predicate, Sensitivity
from acxes.pdp.subject_store import SubjectRecord, SubjectStore
from acxes.security_context import SecurityContext

POLICIES_DIR = Path(__file__).resolve().parent / "policies"
ACTIVE_POLICY = POLICIES_DIR / "2026-09-21.1.yaml"

Action = Literal["search", "read"]


class _RolePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_sensitivity: Literal["publico", "interno", "confidencial"]
    depts: tuple[str, ...]
    own_dept: bool


class _Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}\.\d+$")
    depts: tuple[str, ...] = Field(min_length=1)
    roles: dict[str, _RolePolicy] = Field(min_length=1)
    permissions: dict[str, dict[str, tuple[str, ...]]]

    @model_validator(mode="after")
    def _consistent(self) -> "_Policy":
        for name, role in self.roles.items():
            unknown = set(role.depts) - set(self.depts)
            if unknown:
                raise ValueError(f"rol {name}: dependencias fuera del catálogo {unknown}")
        for resource, actions in self.permissions.items():
            for action, roles in actions.items():
                if set(roles) - set(self.roles):
                    raise ValueError(f"{resource}.{action}: rol desconocido")
        return self


class PolicyDecisionPoint:
    def __init__(
        self,
        subjects: SubjectStore,
        policy_path: Path = ACTIVE_POLICY,
        clock: Callable[[], float] = time.monotonic,
        timeout_s: float = 0.5,
    ) -> None:
        self._subjects = subjects
        self._clock = clock
        self._timeout_s = timeout_s
        self._policy = _load(policy_path)

    @property
    def policy_version(self) -> str | None:
        """Versión activa, para que la API de borde la ponga en el SecurityContext.
        None si no hay política válida, y en ese caso todo se deniega."""
        return self._policy.version if self._policy else None

    def evaluate(self, ctx: SecurityContext, action: str, resource: str) -> Decision:
        started = self._clock()
        try:
            decision = self._evaluate(ctx, action, resource)
        except Exception:  # noqa: BLE001  cualquier fallo deniega (P14)
            return self._deny("error")
        if self._clock() - started > self._timeout_s:
            return self._deny("timeout")
        return decision

    def _evaluate(self, ctx: SecurityContext, action: str, resource: str) -> Decision:
        policy = self._policy
        if policy is None:
            return self._deny("no_policy")
        if ctx.policy_version != policy.version:
            return self._deny("policy_version")
        try:
            subject = self._subjects.lookup(ctx.user_id)
        except Exception:  # noqa: BLE001  un fallo del almacén deniega (P14)
            return self._deny("subject_error")
        if subject is None:
            return self._deny("unknown_user")
        # P8: exactamente un rol reconocido en la base
        recognized = [r for r in dict.fromkeys(subject.roles) if r in policy.roles]
        if len(recognized) != 1:
            return self._deny("roles")
        role = recognized[0]
        # P9
        if subject.dept not in policy.depts:
            return self._deny("dept")
        # P7: el nivel sale del rol de la base
        rule = policy.roles[role]
        # P11
        if role not in policy.permissions.get(resource, {}).get(action, ()):
            return self._deny("action")

        depts = rule.depts + ((subject.dept,) if rule.own_dept else ())
        predicate = Predicate(
            allowed_depts=tuple(dict.fromkeys(depts)),
            max_sensitivity=Sensitivity[rule.max_sensitivity],
            owner_id=ctx.user_id,
            acl_tags=tuple(dict.fromkeys(subject.acl_tags)),
        )
        # Nunca se concede restringido por nivel. Si ocurriera, se deniega
        if predicate.max_sensitivity >= Sensitivity.restringido:
            return self._deny("invariant")
        return Decision(
            decision="allow",
            policy_version=policy.version,
            evaluated_at=datetime.now(UTC),
            predicate=predicate,
            role=role,
            dept=subject.dept,
            claims_drift=_claims_drift(ctx, subject, role, rule.max_sensitivity, policy),
        )

    def _deny(self, reason: str) -> Decision:
        return Decision(
            decision="deny",
            policy_version=self.policy_version or "",
            evaluated_at=datetime.now(UTC),
            reason=reason,
        )


def _claims_drift(
    ctx: SecurityContext, subject: SubjectRecord, role: str, clearance: str, policy: _Policy
) -> tuple[str, ...]:
    """Claims del token que no coinciden con la base. No cambian la decisión."""
    token_roles = {r for r in ctx.roles if r in policy.roles}
    drift = []
    if token_roles != {role}:
        drift.append("roles")
    if ctx.dept != subject.dept:
        drift.append("dept")
    if ctx.clearance != clearance:
        drift.append("clearance")
    if set(ctx.acl_tags) != set(subject.acl_tags):
        drift.append("acl_tags")
    return tuple(drift)


def _load(path: Path) -> _Policy | None:
    """Carga y valida la política. Ante cualquier fallo devuelve None y el PDP deniega todo."""
    try:
        policy = _Policy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001  una política ilegible deja al PDP denegando todo
        return None
    # El nombre del archivo es la versión, para que no se active una política por error
    return policy if path.stem == policy.version else None
