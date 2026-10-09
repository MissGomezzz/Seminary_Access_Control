"""Validación OIDC de tokens para la API de borde.

La clave se obtiene del JWKS del emisor y se reutiliza mediante ``PyJWKClient``.
Ningún claim del token decide autorización: después de validar el token se construye
un ``SecurityContext`` y el PDP consulta los atributos vigentes en la base.
"""

from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient

from acxes.config import Settings
from acxes.security_context import SecurityContext


class OIDCAuthenticator:
    def __init__(self, settings: Settings) -> None:
        if not settings.oidc_issuer or not settings.oidc_jwks_url:
            raise ValueError("OIDC_ISSUER y OIDC_JWKS_URL son obligatorios")
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._jwks = PyJWKClient(settings.oidc_jwks_url, cache_jwk_set=True, lifespan=300)
        self._audience = settings.oidc_audience
        self._client_id = settings.oidc_client_id
        self._algorithms = list(settings.oidc_algorithms)

    def authenticate(self, token: str, policy_version: str) -> SecurityContext:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
            azp = claims.get("azp")
            if azp is not None and azp != self._client_id:
                raise ValueError("azp inválido")
            return SecurityContext.from_claims(claims, policy_version=policy_version)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=401, detail="Token inválido") from exc


@lru_cache(maxsize=1)
def authenticator(settings_key: tuple[str, ...]) -> OIDCAuthenticator:
    settings = Settings(
        oidc_issuer=settings_key[0],
        oidc_jwks_url=settings_key[1],
        oidc_audience=settings_key[2],
        oidc_client_id=settings_key[3],
    )
    return OIDCAuthenticator(settings)
