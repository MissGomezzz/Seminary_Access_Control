"""API de borde y monolito de ACXES: un solo proceso sirve el front y la API.

Uso:
    uvicorn acxes.edge_api.app:app --reload --port 8000     # abrir http://localhost:8000

El modo se elige con `ACXES_MODE` en `.env` (ver documents/FRONTEND.md):

    demo      Sin Docker ni base de datos. Un motor de prueba responde con plantillas. No es la
              arquitectura Secure.
    dev       Agente S real (PDP, Tool Gateway, RLS, modelo de LLM_CLIENT) con sesiones de prueba
              emitidas por este proceso, sin Keycloak. Solo para desarrollo: cualquiera que llegue
              al puerto puede entrar como cualquiera de los seis usuarios de prueba.
    keycloak  Agente S real y tokens RS256 de Keycloak, validados en cada petición.

API que consume `acxes/web/`:

    GET  /api/health       estado del proceso
    GET  /api/config       configuración pública (modo, Keycloak, usuarios de prueba)
    POST /api/demo/login   solo en demo y dev: emite una sesión de prueba
    GET  /api/me           perfil efectivo, calculado por el PDP
    POST /api/chat         un turno del asistente

El cuerpo de /api/chat solo admite `message` y `conversation_id`. La identidad sale únicamente
del token, nunca del cuerpo. Las respuestas de error son genéricas (P14): el motivo real queda
en el registro del servidor.
"""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from acxes.config import Settings, get_settings
from acxes.edge_api import demo_engine
from acxes.edge_api.errors import AccessDenied, BackendUnavailable, InvalidIdentity
from acxes.edge_api.jwt_validator import (
    KeycloakTokenValidator,
    TokenError,
    build_keycloak_validator,
)
from acxes.edge_api.ratelimit import SlidingWindowLimiter
from acxes.edge_api.service import ChatService

log = logging.getLogger("acxes.edge")

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

MSG_TOKEN = "Token inválido o expirado."
MSG_IDENTITY = "No se pudo verificar tu identidad."
MSG_DENIED = "Tu cuenta no tiene acceso al asistente."
MSG_UNAVAILABLE = "El asistente no está disponible en este momento."
MSG_RATE = "Demasiadas solicitudes. Espera un momento."


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # el cliente no puede mandar identidad ni rol
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


def create_app(
    settings: Settings | None = None,
    *,
    service: ChatService | None = None,
    validator: KeycloakTokenValidator | None = None,
) -> FastAPI:
    """Arma la aplicación. `service` y `validator` se inyectan en las pruebas."""
    settings = settings or get_settings()
    mode = settings.acxes_mode
    limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)
    issuer = f"{settings.keycloak_public_url.rstrip('/')}/realms/{settings.keycloak_realm}"
    lazy: dict = {"service": service, "validator": validator}
    lock = threading.Lock()

    def get_service() -> ChatService:
        """El stack de S se arma una vez por proceso y solo en los modos con agente real."""
        with lock:
            if lazy["service"] is None:
                from acxes.secure_app import build_secure_stack

                stack = build_secure_stack(settings)
                names = demo_engine.display_name if mode == "dev" else None
                lazy["service"] = ChatService(stack.agent, stack.pdp, stack.retrieval, names)
            return lazy["service"]

    def get_validator() -> KeycloakTokenValidator:
        with lock:
            if lazy["validator"] is None:
                lazy["validator"] = build_keycloak_validator(
                    issuer=issuer,
                    audience=settings.keycloak_api_audience,
                    authorized_party=settings.keycloak_web_client_id,
                    jwks_url=settings.keycloak_jwks_url
                    or f"{issuer}/protocol/openid-connect/certs",
                )
            return lazy["validator"]

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if mode != "demo":  # falla al arrancar, y no en la primera petición, si la configuración es mala
            svc = get_service()
            log.info(
                "ACXES modo=%s política=%s modelo=%s", mode, svc.policy_version, settings.llm_client
            )
        if mode == "keycloak":
            get_validator()
            log.info("ACXES Keycloak emisor=%s audiencia=%s", issuer, settings.keycloak_api_audience)
        yield

    app = FastAPI(
        title="ACXES",
        version="0.2.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------ errores genéricos
    @app.exception_handler(InvalidIdentity)
    def _invalid_identity(_req: Request, _exc: InvalidIdentity) -> JSONResponse:
        return JSONResponse({"detail": MSG_IDENTITY}, status_code=401)

    @app.exception_handler(AccessDenied)
    def _denied(_req: Request, _exc: AccessDenied) -> JSONResponse:
        return JSONResponse({"detail": MSG_DENIED}, status_code=403)

    @app.exception_handler(BackendUnavailable)
    def _unavailable(_req: Request, _exc: BackendUnavailable) -> JSONResponse:
        return JSONResponse({"detail": MSG_UNAVAILABLE}, status_code=503)

    @app.exception_handler(Exception)
    def _unexpected(_req: Request, exc: Exception) -> JSONResponse:
        log.exception("edge: error no controlado (%s)", type(exc).__name__)
        return JSONResponse({"detail": "Error interno."}, status_code=500)

    # ------------------------------------------------------------ autenticación
    def require_claims(authorization: Annotated[str | None, Header()] = None) -> dict:
        """Autentica la petición y devuelve los claims. El resto del sistema no ve el JWT."""
        headers = {"WWW-Authenticate": "Bearer"}
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Falta el token.", headers=headers)
        token = authorization[7:].strip()
        if mode == "keycloak":
            try:
                return get_validator().validate(token)
            except TokenError as exc:
                log.warning("edge: token rechazado (%s)", exc.reason)
                raise HTTPException(401, MSG_TOKEN, headers=headers) from exc
        claims = demo_engine.verify_demo_token(token)
        if claims is None:
            raise HTTPException(401, MSG_TOKEN, headers=headers)
        return claims

    Claims = Annotated[dict, Depends(require_claims)]

    # ------------------------------------------------------------ rutas
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "mode": mode}

    @app.get("/api/config")
    def get_config() -> dict:
        policy = demo_engine.POLICY_VERSION
        if mode != "demo":
            try:
                policy = get_service().policy_version
            except Exception:  # la configuración debe poder leerse aunque la base esté caída
                log.exception("edge: no se pudo armar el stack de S")
                policy = None
        return {
            "mode": mode,
            "demo": mode != "keycloak",
            "keycloak": {
                "url": settings.keycloak_public_url,
                "realm": settings.keycloak_realm,
                "clientId": settings.keycloak_web_client_id,
            },
            "policy_version": policy,
            "demo_users": [
                {
                    "id": u.id,
                    "full_name": u.full_name,
                    "role": u.role,
                    "dept": u.dept,
                    "clearance": u.clearance,
                    "acl_tags": list(u.acl_tags),
                }
                for u in demo_engine.DEMO_USERS
            ]
            if mode != "keycloak"
            else [],
        }

    @app.post("/api/demo/login")
    def demo_login(body: DemoLoginRequest) -> dict:
        if mode == "keycloak":
            raise HTTPException(404)
        user = next((u for u in demo_engine.DEMO_USERS if u.id == body.user_id), None)
        if user is None:
            raise HTTPException(404, "Usuario de prueba desconocido.")
        return demo_engine.issue_demo_token(user)

    @app.get("/api/me")
    def me(claims: Claims) -> dict:
        if mode == "demo":
            return demo_engine.profile(claims)
        return get_service().profile(claims)

    @app.post("/api/chat")
    def chat(body: ChatRequest, claims: Claims) -> dict:
        if not limiter.allow(str(claims.get("sub"))):  # P13
            raise HTTPException(429, MSG_RATE)
        if mode == "demo":
            return demo_engine.answer(claims, body.message)
        return get_service().chat(claims, body.message)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
    return app


app = create_app()
