"""El motor de demo debe aplicar exactamente la regla de POLITICAS_ACCESO.md, porque el
front se construye y se prueba sobre él. Sin red, sin Docker."""

import pytest
from fastapi.testclient import TestClient

from acxes.edge_api import demo_engine as de
from acxes.edge_api.app import app

USERS = {u.full_name: u for u in de.DEMO_USERS}


def _claims(name: str) -> dict:
    tok = de.issue_demo_token(USERS[name])["access_token"]
    claims = de.verify_demo_token(tok)
    assert claims is not None
    return claims


def _visible(name: str) -> set[str]:
    pred = de.build_predicate(_claims(name))
    return {d.slug for d in de.load_corpus() if de.is_visible(d, pred)}


def _by_slug(slug: str) -> de.Doc:
    return next(d for d in de.load_corpus() if d.slug == slug)


def test_empleado_no_ve_confidencial_ajeno_ni_restringido():
    vis = _visible("Sofía Ariza")
    assert "nomina-individual-sofia-ariza" in vis  # P3: registro propio
    assert "nomina-individual-laura-martinez" not in vis
    assert not any(_by_slug(s).sensitivity == "restringido" for s in vis)


def test_restringido_solo_con_etiqueta_coincidente():
    carlos = _visible("Carlos Rentería")  # comite_disciplinario
    laura = _visible("Laura Martínez")  # auditoria_interna
    admin = _visible("Diego Fajardo")  # sin etiquetas (P6)
    acta = "acta-del-comite-disciplinario-2026-01"
    assert acta in carlos
    assert acta not in laura
    assert acta not in admin


def test_administrador_ve_las_tres_dependencias_hasta_confidencial():
    vis = {_by_slug(s).dept for s in _visible("Diego Fajardo")}
    assert vis == set(de.DEPTS)


def test_p4_restringido_sin_etiquetas_no_lo_ve_nadie():
    sin_etiquetas = [d for d in de.load_corpus() if d.sensitivity == "restringido" and not d.acl_tags]
    assert sin_etiquetas
    for name in USERS:
        for d in sin_etiquetas:
            assert d.slug not in _visible(name)


def test_p7_clearance_incoherente_se_deniega():
    claims = _claims("Sofía Ariza") | {"clearance": "confidencial"}
    with pytest.raises(de.Denied):
        de.build_predicate(claims)


def test_p8_exactamente_un_rol_reconocido():
    claims = _claims("Sofía Ariza") | {"realm_access": {"roles": ["empleado", "administrador"]}}
    with pytest.raises(de.Denied):
        de.build_predicate(claims)


def test_p12_inexistente_y_no_autorizado_dan_la_misma_respuesta():
    empleado = _claims("Sofía Ariza")
    pred = de.build_predicate(empleado)
    vistos = " ".join(de._norm(d.body + d.title) for d in de.load_corpus() if de.is_visible(d, pred))
    ajeno = _by_slug("nomina-individual-laura-martinez")
    # palabras que solo existen en el documento prohibido: ninguna fuente visible las contiene
    exclusivas = [t for t in de._tokens(ajeno.body) if t not in vistos][:3]
    assert exclusivas
    prohibido = de.answer(empleado, " ".join(exclusivas))
    inexistente = de.answer(empleado, "zzzxqk plumbus")
    assert prohibido["answer"] == inexistente["answer"] == de.DENIAL
    assert prohibido["citations"] == inexistente["citations"] == []


def test_token_de_demo_manipulado_es_rechazado():
    tok = de.issue_demo_token(USERS["Sofía Ariza"])["access_token"]
    head, _body, sig = tok.split(".")
    forjado = de._b64(b'{"sub":"x","aud":"acxes-chat-api","exp":9999999999}')
    assert de.verify_demo_token(f"{head}.{forjado}.{sig}") is None


def test_api_flujo_login_demo_me_y_chat():
    client = TestClient(app)
    cfg = client.get("/api/config").json()
    assert cfg["demo"] is True and len(cfg["demo_users"]) == 6

    uid = USERS["Ángela Gómez"].id
    token = client.post("/api/demo/login", json={"user_id": uid}).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/me", headers=auth).json()["full_name"] == "Ángela Gómez"
    r = client.post("/api/chat", json={"message": "reglamento estudiantil matrícula"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["gateway"]["decision"] == "allow"
    assert r.json()["citations"]


def test_api_rechaza_sin_token_y_campos_de_identidad_en_el_cuerpo():
    client = TestClient(app)
    assert client.post("/api/chat", json={"message": "hola"}).status_code == 401
    uid = USERS["Sofía Ariza"].id
    token = client.post("/api/demo/login", json={"user_id": uid}).json()["access_token"]
    r = client.post(
        "/api/chat",
        json={"message": "hola", "role": "administrador"},  # el cliente no manda identidad
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_mi_nomina_prioriza_el_registro_propio():
    r = de.answer(_claims("Sofía Ariza"), "Muéstrame mi nómina individual")
    assert r["citations"][0]["doc_id"] == "nomina-individual-sofia-ariza"
    assert all(c["doc_id"] != "nomina-individual-laura-martinez" for c in r["citations"])
