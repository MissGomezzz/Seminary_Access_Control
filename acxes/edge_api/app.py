"""Monolito de ACXES: un solo proceso sirve el front y la API.

Uso:
    uvicorn acxes.edge_api.app:app --reload --port 8000
    # abrir http://localhost:8000

Contrato de la API (lo que consume `acxes/web/`):

    GET  /api/config        -> configuración pública (Keycloak, modo demo)
    GET  /api/me            -> perfil derivado del token
    POST /api/chat          -> un turno del asistente (ver `documents/FRONTEND.md`)
    POST /api/demo/login    -> solo en modo demo: emite un token de demo

Modo demo (`ACXES_FRONT_DEMO=1`, por defecto): usa `demo_engine`, que NO es la
arquitectura Secure. Con `ACXES_FRONT_DEMO=0` los endpoints protegidos responden 501
hasta que se implemente la API de borde real (validación de JWT, SecurityContext,
orquestador S, Tool Gateway + PDP, guardia de salida). Ver los TODO(etapa N) abajo.
"""

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from acxes.edge_api import demo_engine

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
DEMO = os.environ.get("ACXES_FRONT_DEMO", "1") == "1"
KEYCLOAK_URL = os.environ.get(
    "KEYCLOAK_PUBLIC_URL", f"http://localhost:{os.environ.get('KEYCLOAK_PORT', '8080')}"
)
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "acxes")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_WEB_CLIENT_ID", "acxes-chat-web")

app = FastAPI(title="ACXES", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # el cliente no puede mandar identidad ni rol
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


def _require_claims(authorization: str | None = Header(default=None)) -> dict:
    """Autentica la petición. En demo valida el token de demo.

    TODO(etapa 2): validar el JWT de Keycloak (RS256 contra el JWKS, `iss`, `aud`, `exp`,
    `nbf`, `azp`, rechazo de `alg: none`) y construir el SecurityContext. El resto del
    sistema solo debe ver el SecurityContext, nunca el JWT.
    """
    if not DEMO:
        raise HTTPException(501, "API de borde real pendiente (etapa 2). Use ACXES_FRONT_DEMO=1.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Falta el token")
    claims = demo_engine.verify_demo_token(authorization[7:].strip())
    if claims is None:
        raise HTTPException(401, "Token inválido o expirado")
    return claims


Claims = Annotated[dict, Depends(_require_claims)]


@app.get("/api/config")
def get_config() -> dict:
    return {
        "demo": DEMO,
        "keycloak": {"url": KEYCLOAK_URL, "realm": KEYCLOAK_REALM, "clientId": KEYCLOAK_CLIENT_ID},
        "policy_version": demo_engine.POLICY_VERSION,
        "demo_users": (
            [
                {
                    "id": u.id, "full_name": u.full_name, "role": u.role, "dept": u.dept,
                    "clearance": u.clearance, "acl_tags": list(u.acl_tags),
                }
                for u in demo_engine.DEMO_USERS
            ]
            if DEMO
            else []
        ),
    }


@app.post("/api/demo/login")
def demo_login(body: DemoLoginRequest) -> dict:
    if not DEMO:
        raise HTTPException(404)
    user = next((u for u in demo_engine.DEMO_USERS if u.id == body.user_id), None)
    if user is None:
        raise HTTPException(404, "Usuario de demo desconocido")
    return demo_engine.issue_demo_token(user)


@app.get("/api/me")
def me(claims: Claims) -> dict:
    return demo_engine.profile(claims)


@app.post("/api/chat")
def chat(body: ChatRequest, claims: Claims) -> dict:
    # TODO(etapa 4/5): reemplazar demo_engine.answer por el orquestador S:
    #   SecurityContext -> LLM -> Tool Gateway -> PDP -> retrieval (RLS) -> guardia de salida.
    if demo_engine.rate_limited(claims["sub"]):  # P13: 30 solicitudes por minuto
        raise HTTPException(429, "Demasiadas solicitudes. Espera un momento.")
    return demo_engine.answer(claims, body.message)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
