"""Botón de Keycloak: lo que la API debe garantizar para que el front funcione.

Sin red ni base de datos. El recorrido real con un Keycloak encendido se prueba a mano
(documents/CONEXION_FRONT_BACK.md, sección "Probar el botón de Keycloak").
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from acxes.config import Settings
from acxes.edge_api.app import create_app
from acxes.edge_api.jwt_validator import TokenError
from acxes.edge_api.service import ChatService, _claim_name
from acxes.pdp.model import Decision, Predicate, Sensitivity

SECRETS = {
    "postgres_password": "x",
    "postgres_app_password": "x",
    "postgres_audit_password": "x",
    "postgres_pdp_password": "x",
    "keycloak_admin_password": "x",
}
USER = "00000000-0000-4000-a000-000000000001"
CLAIMS = {
    "sub": USER,
    "name": "Sofía Ariza",
    "realm_access": {"roles": ["empleado"]},
    "dept": "financiera",
    "clearance": "interno",
    "sid": "sesion-1",
}


class FakePdp:
    policy_version = "2026-09-21.1"

    def evaluate(self, ctx, action, resource):
        pred = Predicate(("institucional", "financiera"), Sensitivity.interno, UUID(USER), ())
        return Decision(
            "allow",
            self.policy_version,
            datetime.now(UTC),
            pred,
            role="empleado",
            dept="financiera",
        )


class FakeValidator:
    def validate(self, token):
        if token != "token-bueno":
            raise TokenError("InvalidSignatureError")
        return dict(CLAIMS)


def _client(mode: str, **extra) -> TestClient:
    service = ChatService(agent=None, pdp=FakePdp(), retrieval=None)
    settings = Settings(acxes_mode=mode, **(SECRETS if mode == "keycloak" else {}), **extra)
    return TestClient(create_app(settings, service=service, validator=FakeValidator()))


@pytest.mark.parametrize(("mode", "sso"), [("demo", False), ("dev", False), ("keycloak", True)])
def test_config_dice_si_el_boton_de_keycloak_sirve(mode, sso):
    cfg = _client(mode).get("/api/config").json()
    assert cfg["sso"] is sso
    assert cfg["mode"] == mode
    assert cfg["keycloak"]["clientId"] == "acxes-chat-web"


def test_en_keycloak_no_hay_sesiones_de_prueba():
    client = _client("keycloak")
    assert client.get("/api/config").json()["demo_users"] == []
    assert client.post("/api/demo/login", json={"user_id": USER}).status_code == 404


def test_token_de_keycloak_invalido_es_401_generico():
    r = _client("keycloak").get("/api/me", headers={"Authorization": "Bearer falso"})
    assert r.status_code == 401
    assert "InvalidSignature" not in r.text  # no filtra el motivo


def test_me_muestra_el_nombre_del_claim_de_keycloak():
    me = _client("keycloak").get("/api/me", headers={"Authorization": "Bearer token-bueno"}).json()
    assert me["full_name"] == "Sofía Ariza"
    assert me["roles"] == ["empleado"]  # sale del PDP, no del token
    assert me["allowed_depts"] == ["institucional", "financiera"]


@pytest.mark.parametrize(
    ("claims", "esperado"),
    [
        ({"name": "  Laura   Martínez "}, "Laura Martínez"),
        ({"name": "x" * 500}, "x" * 80),
        ({"name": ""}, None),
        ({"name": 123}, None),
        ({"name": ["Laura"]}, None),
        ({}, None),
    ],
)
def test_el_nombre_del_token_solo_se_usa_como_texto_para_mostrar(claims, esperado):
    assert _claim_name(claims) == esperado
