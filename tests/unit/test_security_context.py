from uuid import UUID

import pytest
from pydantic import ValidationError

from acxes.security_context import SecurityContext

SUB = "00000000-0000-4000-a000-000000000004"


def _claims(**over) -> dict:
    claims = {
        "sub": SUB,
        "realm_access": {"roles": ["supervisor", "default-roles-acxes"]},
        "dept": "financiera",
        "clearance": "confidencial",
        "acl_tags": ["auditoria_interna"],
        "sid": "s-1",
    }
    claims.update(over)
    return claims


def test_se_construye_desde_los_claims_de_keycloak():
    ctx = SecurityContext.from_claims(_claims(), policy_version="2026-09-21.1")

    assert ctx.user_id == UUID(SUB)
    assert ctx.roles == ("supervisor", "default-roles-acxes")
    assert ctx.dept == "financiera"
    assert ctx.clearance == "confidencial"
    assert ctx.acl_tags == ("auditoria_interna",)
    assert ctx.session_id == "s-1"
    assert ctx.policy_version == "2026-09-21.1"


def test_session_id_tiene_prioridad_sobre_sid():
    ctx = SecurityContext.from_claims(_claims(session_id="s-2"), policy_version="v")
    assert ctx.session_id == "s-2"


def test_acl_tags_ausente_equivale_a_ninguna_etiqueta():
    claims = _claims()
    del claims["acl_tags"]
    assert SecurityContext.from_claims(claims, policy_version="v").acl_tags == ()


def test_es_inmutable():
    ctx = SecurityContext.from_claims(_claims(), policy_version="v")
    with pytest.raises(ValidationError):
        ctx.dept = "academica"


def test_no_admite_campos_adicionales():
    with pytest.raises(ValidationError):
        SecurityContext(
            user_id=UUID(SUB),
            roles=("empleado",),
            dept="financiera",
            clearance="interno",
            session_id="s",
            policy_version="v",
            is_admin=True,
        )


@pytest.mark.parametrize(
    "over",
    [
        {"sub": None},
        {"sub": "no-es-uuid"},
        {"dept": ""},
        {"clearance": 3},
        {"sid": None},
        {"acl_tags": "auditoria_interna"},
        {"acl_tags": [1]},
        {"realm_access": {"roles": "supervisor"}},
        {"realm_access": "supervisor"},
    ],
)
def test_claims_con_tipo_inesperado_se_rechazan(over):
    with pytest.raises(ValueError):
        SecurityContext.from_claims(_claims(**over), policy_version="v")
