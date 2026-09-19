from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída del entorno. Los secretos solo viven en .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Modelo de lenguaje, sin acoplarse a un proveedor concreto
    llm_client: Literal["mock", "real"] = "mock"
    llm_provider: str = ""
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model_agent: str = ""
    llm_model_bulk: str = ""

    # Base de datos: el orquestador no recibe ninguna de estas credenciales
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "acxes"


def get_settings() -> Settings:
    return Settings()
