"""Validación del access token de Keycloak (etapa 2, docs/ARQUITECTURA.md 4.2).

Se valida una sola vez, en la API de borde y en cada petición. De aquí en adelante el sistema
trabaja con el `SecurityContext` y nunca con el JWT.

Se comprueba: firma RS256 contra el JWKS del realm (con caché y rotación por `kid`), `iss`,
`aud`, `exp`, `nbf`, `iat`, `azp` y `typ`. Se rechaza `alg: none` y cualquier algoritmo distinto
de RS256, incluido el ataque de confusión que firma con HS256 usando la clave pública.

Todo fallo lanza `TokenError`. El motivo sirve para el registro del servidor y no sale al
cliente. Si el JWKS no se puede obtener, se rechaza el token (fail-closed).
"""

import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

MAX_TOKEN_CHARS = 8192  # un access token de Keycloak mide unos pocos KB


class TokenError(Exception):
    """Token rechazado. `reason` es un código corto para el registro, nunca para el usuario."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _fetch_jwks(url: str, timeout_s: float = 5.0) -> dict:
    response = httpx.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


class JwksCache:
    """Conjunto de claves públicas del realm.

    Se renueva al vencer `ttl_s` o cuando llega un `kid` desconocido (rotación de claves). La
    renovación por `kid` desconocido tiene un intervalo mínimo: sin él, quien no tiene cuenta
    podría forzar una petición a Keycloak por cada token falso que envíe.
    """

    def __init__(
        self,
        url: str,
        fetch: Callable[[str], dict] = _fetch_jwks,
        ttl_s: float = 300.0,
        min_refresh_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._fetch = fetch
        self._ttl_s = ttl_s
        self._min_refresh_s = min_refresh_s
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        keyset = PyJWKSet.from_dict(self._fetch(self._url))
        self._keys = {k.key_id: k for k in keyset.keys if k.key_id}
        self._fetched_at = self._clock()

    def key_for(self, kid: str) -> Any:
        with self._lock:
            now = self._clock()
            try:
                if self._fetched_at is None or now - self._fetched_at >= self._ttl_s:
                    self._refresh()
                elif kid not in self._keys and now - self._fetched_at >= self._min_refresh_s:
                    # Rotación de claves: un `kid` nuevo, como máximo cada `min_refresh_s`
                    self._refresh()
            except Exception as exc:
                raise TokenError("jwks_unavailable") from exc
            jwk = self._keys.get(kid)
        if jwk is None:
            raise TokenError("unknown_kid")
        return jwk.key


class KeycloakTokenValidator:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        authorized_party: str,
        keys: JwksCache,
        leeway_s: int = 10,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._azp = authorized_party
        self._keys = keys
        self._leeway_s = leeway_s

    def validate(self, token: str) -> dict:
        """Devuelve los claims si el token es válido. Lanza `TokenError` en cualquier otro caso."""
        if not token or len(token) > MAX_TOKEN_CHARS:
            raise TokenError("size")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenError("malformed") from exc
        # Solo RS256. Cubre `none` y la confusión RS256/HS256
        if header.get("alg") != "RS256":
            raise TokenError("alg")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenError("kid")

        key = self._keys.key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError(type(exc).__name__) from exc

        if claims.get("azp") != self._azp:
            raise TokenError("azp")
        # Un ID token o un refresh token no sirven como credencial de la API
        if claims.get("typ") != "Bearer":
            raise TokenError("typ")
        return claims


def build_keycloak_validator(
    *, issuer: str, audience: str, authorized_party: str, jwks_url: str
) -> KeycloakTokenValidator:
    return KeycloakTokenValidator(
        issuer=issuer,
        audience=audience,
        authorized_party=authorized_party,
        keys=JwksCache(jwks_url),
    )
