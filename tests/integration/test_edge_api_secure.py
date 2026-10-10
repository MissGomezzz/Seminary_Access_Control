"""La API de borde con el agente S real (PDP, Tool Gateway, RLS) y el modelo simulado.

Corre en modo `dev`, que emite sesiones de prueba sin Keycloak. Requiere la base aplicada
(`python -m acxes.db.apply`). La validación de tokens de Keycloak se prueba aparte, en
tests/unit/test_jwt_validator.py.
"""

import pytest
from fastapi.testclient import TestClient

from acxes.config import Settings
from acxes.edge_api import demo_engine as de
from acxes.edge_api.app import create_app

pytestmark = pytest.mark.db

DENIAL = "No encontré información disponible para tu perfil sobre esa consulta."
USERS = {u.full_name: u for u in de.DEMO_USERS}


@pytest.fixture(scope="module")
def client():
    settings = Settings(acxes_mode="dev", llm_client="mock", rate_limit_per_minute=1000)
    with TestClient(create_app(settings)) as c:
        yield c


def _login(client: TestClient, name: str) -> dict:
    token = client.post("/api/demo/login", json={"user_id": USERS[name].id}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_config_informa_el_modo_y_la_politica_del_pdp(client):
    cfg = client.get("/api/config").json()
    assert cfg["mode"] == "dev"
    assert cfg["policy_version"]
    assert len(cfg["demo_users"]) == 6


def test_me_sale_del_pdp_y_no_de_los_claims(client):
    me = client.get("/api/me", headers=_login(client, "Carlos Rentería")).json()
    assert me["full_name"] == "Carlos Rentería"
    assert me["roles"] == ["supervisor"]
    assert me["acl_tags"] == ["comite_disciplinario"]
    assert me["policy_version"] == client.get("/api/config").json()["policy_version"]


def test_chat_responde_con_el_contrato_del_front(client):
    r = client.post(
        "/api/chat",
        json={"message": "reglamento estudiantil matrícula"},
        headers=_login(client, "Ángela Gómez"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["gateway"]["engine"] == "secure"
    assert body["gateway"]["decision"] == "allow"
    assert body["gateway"]["output_guard"] == "pending"  # la etapa 5 aún no existe
    assert {"answer", "status", "citations", "gateway"} <= body.keys()
    for c in body["citations"]:
        assert {"doc_id", "title", "dept", "sensitivity", "acl_tags", "chunk_ids"} <= c.keys()


def test_el_empleado_no_recibe_fuentes_restringidas_ni_ajenas(client):
    r = client.post(
        "/api/chat",
        json={"message": "acta comité disciplinario nómina individual salario"},
        headers=_login(client, "Sofía Ariza"),
    ).json()
    assert all(c["sensitivity"] in ("publico", "interno", "confidencial") for c in r["citations"])
    assert not any(c["sensitivity"] == "restringido" for c in r["citations"])
    titulos = " ".join(c["title"].lower() for c in r["citations"])
    assert "laura martínez" not in titulos and "laura martinez" not in titulos


def test_inexistente_no_devuelve_fuentes_y_lo_prohibido_no_se_filtra(client):
    """P12: lo que no existe no devuelve nada, y una consulta sobre material prohibido solo
    puede traer fuentes que el empleado sí puede ver (aquí, públicas sobre el mismo tema)."""
    h = _login(client, "Sofía Ariza")
    inexistente = client.post("/api/chat", json={"message": "zzzxqk plumbus wibblefrop"}, headers=h).json()
    assert inexistente["citations"] == []
    assert inexistente["status"] == "no_results"
    assert inexistente["gateway"]["chunks"] == 0

    prohibido = client.post(
        "/api/chat", json={"message": "acta comité disciplinario sanción"}, headers=h
    ).json()
    assert all(c["sensitivity"] in ("publico", "interno") for c in prohibido["citations"])
    assert not any(c["acl_tags"] for c in prohibido["citations"])


def test_el_cuerpo_no_puede_traer_identidad(client):
    r = client.post(
        "/api/chat",
        json={"message": "hola", "role": "administrador"},
        headers=_login(client, "Sofía Ariza"),
    )
    assert r.status_code == 422


def test_sin_token_o_con_token_falso_es_401(client):
    assert client.post("/api/chat", json={"message": "hola"}).status_code == 401
    r = client.post(
        "/api/chat", json={"message": "hola"}, headers={"Authorization": "Bearer a.b.c"}
    )
    assert r.status_code == 401


def test_usuario_inexistente_en_la_base_no_obtiene_acceso(client):
    fantasma = de.DemoUser(
        "00000000-0000-4000-a000-0000000000ff", "Fantasma", "empleado", "financiera", "interno", ()
    )
    token = de.issue_demo_token(fantasma)["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/chat", json={"message": "reglamento"}, headers=h)
    assert r.status_code in (403, 200)
    if r.status_code == 200:
        assert r.json()["citations"] == []
    assert client.get("/api/me", headers=h).status_code == 403


def test_limite_de_solicitudes_por_usuario():
    settings = Settings(acxes_mode="dev", llm_client="mock", rate_limit_per_minute=2)
    with TestClient(create_app(settings)) as c:
        h = _login(c, "Belén Quintero")
        codigos = [
            c.post("/api/chat", json={"message": "reglamento"}, headers=h).status_code
            for _ in range(3)
        ]
    assert codigos == [200, 200, 429]
