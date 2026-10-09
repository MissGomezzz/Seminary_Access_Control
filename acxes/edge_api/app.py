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
import re
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from acxes.config import get_settings
from acxes.edge_api import demo_engine
from acxes.edge_api.auth import OIDCAuthenticator
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.pdp.subject_store import PostgresSubjectStore
from acxes.retrieval.secure import RetrievalDenied, SecureRetrievalService
from acxes.security_context import SecurityContext

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SETTINGS = get_settings()
DEMO = os.environ.get("ACXES_FRONT_DEMO", "0") == "1" and SETTINGS.environment in {
    "development",
    "test",
}
KEYCLOAK_URL = os.environ.get(
    "KEYCLOAK_PUBLIC_URL", f"https://localhost:{os.environ.get('KEYCLOAK_PORT', '8080')}"
)
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "acxes")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_WEB_CLIENT_ID", "acxes-chat-web")

app = FastAPI(
    title="ACXES",
    version="0.1.0",
    docs_url="/api/docs" if SETTINGS.environment != "production" else None,
    openapi_url="/api/openapi.json" if SETTINGS.environment != "production" else None,
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; connect-src 'self' https:; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'",
    )
    return response
_authenticator = (
    OIDCAuthenticator(SETTINGS)
    if not DEMO and SETTINGS.oidc_issuer and SETTINGS.oidc_jwks_url
    else None
)
_pdp = PolicyDecisionPoint(PostgresSubjectStore(SETTINGS))
_retrieval = SecureRetrievalService(SETTINGS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # el cliente no puede mandar identidad ni rol
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


def _require_claims(authorization: str | None = Header(default=None)) -> dict:
    """Valida un bearer token y devuelve solo claims de demo o un contexto seguro."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Falta el token")
    token = authorization[7:].strip()
    if DEMO:
        claims = demo_engine.verify_demo_token(token)
        if claims is None:
            raise HTTPException(status_code=401, detail="Token inválido o expirado")
        return claims
    if _authenticator is None:
        raise HTTPException(status_code=503, detail="OIDC no está configurado")
    context = _authenticator.authenticate(token, _pdp.policy_version or "")
    return context.model_dump()


Claims = Annotated[dict, Depends(_require_claims)]


@app.get("/api/config")
def get_config() -> dict:
    return {
        "demo": DEMO,
        "keycloak": {"url": KEYCLOAK_URL, "realm": KEYCLOAK_REALM, "clientId": KEYCLOAK_CLIENT_ID},
        "policy_version": _pdp.policy_version,
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
    if DEMO:
        return demo_engine.profile(claims)
    return {
        "user_id": claims["user_id"],
        "session_id": claims["session_id"],
        "policy_version": claims["policy_version"],
    }


@app.post("/api/chat")
def chat(body: ChatRequest, claims: Claims) -> dict:
    if DEMO:
        if demo_engine.rate_limited(claims["sub"]):
            raise HTTPException(429, "Demasiadas solicitudes. Espera un momento.")
        return demo_engine.answer(claims, body.message)
    context = SecurityContext.model_validate(claims)
    if demo_engine.rate_limited(str(context.user_id)):
        raise HTTPException(429, "Demasiadas solicitudes. Espera un momento.")
    decision = _pdp.evaluate(context, "search", "documentos")
    if not decision.allowed:
        raise HTTPException(status_code=403, detail="Acceso denegado")
    keywords = [word for word in re.findall(r"[\wÁÉÍÓÚÑÜáéíóúñü]+", body.message) if len(word) > 2]
    try:
        hits = _retrieval.search(context, decision, keywords[:8])
    except RetrievalDenied as exc:
        raise HTTPException(status_code=403, detail="Acceso denegado") from exc
    return {
        "answer": "\n\n".join(f"{hit.title}: {hit.content}" for hit in hits)
        or demo_engine.DENIAL,
        "citations": [
            {"doc_id": hit.doc_id, "title": hit.title, "chunk_id": hit.chunk_id} for hit in hits
        ],
        "gateway": {"decision": decision.decision, "policy_version": decision.policy_version},
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
