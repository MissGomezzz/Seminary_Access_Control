from typing import Literal

from psycopg.conninfo import make_conninfo
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DbRole = Literal["owner", "app", "audit", "pdp"]


class Settings(BaseSettings):
    """Configuración leída del entorno. Los secretos solo viven en .env."""

    # hide_input_in_errors evita que un valor mal ubicado en .env (por ejemplo una clave) se
    # imprima en el mensaje de validación
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # Modelo de lenguaje detrás de la interfaz LLMClient
    llm_client: Literal["mock", "real"] = "mock"
    llm_provider: str = ""
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model_agent: str = ""
    llm_model_bulk: str = ""
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3

    # Límites comunes a B1 y S (P13)
    agent_max_iterations: int = 4
    retrieval_k: int = 5
    # Presupuesto de tokens por turno, sumando entrada y salida de todas las iteraciones
    agent_max_turn_tokens: int = 16000

    # Base de datos. Solo la capa de recuperación de S debe usar el rol de aplicación.
    # B1 usa el propietario a propósito, como credencial amplia
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "acxes"
    postgres_user: str = "acxes_owner"
    postgres_password: SecretStr = SecretStr("")
    postgres_app_password: SecretStr = SecretStr("")
    postgres_audit_password: SecretStr = SecretStr("")
    postgres_pdp_password: SecretStr = SecretStr("")

    # API de borde y front (acxes/edge_api/app.py)
    #   demo:     sin Docker. Motor de prueba que no es la arquitectura Secure
    #   dev:      agente S real (PDP, gateway, RLS) con sesiones de prueba, sin Keycloak
    #   keycloak: agente S real y tokens RS256 de Keycloak
    acxes_mode: Literal["demo", "dev", "keycloak"] = "demo"
    keycloak_public_url: str = "http://localhost:8080"
    keycloak_realm: str = "acxes"
    keycloak_web_client_id: str = "acxes-chat-web"
    keycloak_api_audience: str = "acxes-chat-api"
    # Si se deja vacío se usa `{emisor}/protocol/openid-connect/certs`
    keycloak_jwks_url: str = ""
    # P13: solicitudes de chat por usuario y por minuto
    rate_limit_per_minute: int = 30


def get_settings() -> Settings:
    return Settings()


def postgres_dsn(settings: Settings, role: DbRole = "owner") -> str:
    """DSN de conexión para el rol de base de datos indicado. El orquestador de S
    no debe llamar a esto. Solo lo hacen el servicio de recuperación (app), el almacén de
    atributos del PDP (pdp) y B1, que usa el rol propietario por diseño."""
    if role == "owner":
        user, password = settings.postgres_user, settings.postgres_password
    elif role == "app":
        user, password = "acxes_app", settings.postgres_app_password
    elif role == "audit":
        user, password = "acxes_audit", settings.postgres_audit_password
    else:
        user, password = "acxes_pdp", settings.postgres_pdp_password
    return make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=user,
        password=password.get_secret_value(),
        sslmode="disable",
        gssencmode="disable",
        connect_timeout=10,
    )
