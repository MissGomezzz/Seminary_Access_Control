"""Etapa 2: la API de borde rechaza tokens inválidos, expirados o con `aud` incorrecta
(docs/ARQUITECTURA.md, fase 1). Sin red: las claves se generan aquí y el JWKS se simula."""

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from acxes.edge_api.jwt_validator import (
    MAX_TOKEN_CHARS,
    JwksCache,
    KeycloakTokenValidator,
    TokenError,
)

ISSUER = "http://localhost:8080/realms/acxes"
AUDIENCE = "acxes-chat-api"
AZP = "acxes-chat-web"
USER = "00000000-0000-4000-a000-000000000005"


def _b64(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _payload(**extra) -> dict:
    now = int(time.time())
    base = {"sub": USER, "iss": ISSUER, "aud": AUDIENCE, "azp": AZP, "typ": "Bearer"}
    return base | {"iat": now, "exp": now + 600} | extra


class Idp:
    """Un 'Keycloak' mínimo: un par de claves RSA, su JWKS y un emisor de tokens."""

    def __init__(self, kid: str = "k1") -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwk(self) -> dict:
        data = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        return data | {"kid": self.kid, "alg": "RS256", "use": "sig"}

    def token(self, **overrides) -> str:
        claims = _payload(
            aud=[AUDIENCE, "account"],  # Keycloak emite una lista
            sid="sesion-1",
            realm_access={"roles": ["supervisor"]},
            dept="academica",
            clearance="confidencial",
            acl_tags=["comite_disciplinario"],
        )
        claims = {k: v for k, v in (claims | overrides).items() if v is not None}
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": self.kid})


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def idp():
    return Idp()


def _validator(idp: Idp, jwks=None, clock=None, **cache_args):
    fetches = []

    def fetch(url):
        fetches.append(url)
        return jwks() if callable(jwks) else {"keys": [idp.jwk()]}

    cache = JwksCache("http://kc/certs", fetch=fetch, clock=clock or time.monotonic, **cache_args)
    validator = KeycloakTokenValidator(
        issuer=ISSUER, audience=AUDIENCE, authorized_party=AZP, keys=cache
    )
    return validator, fetches


def _rechazado(validator, token, motivo=None):
    with pytest.raises(TokenError) as exc:
        validator.validate(token)
    if motivo:
        assert exc.value.reason == motivo
    return exc.value.reason


# ---------------------------------------------------------------- caso válido
def test_token_valido_devuelve_los_claims(idp):
    claims = _validator(idp)[0].validate(idp.token())
    assert claims["sub"] == USER
    assert claims["realm_access"]["roles"] == ["supervisor"]


def test_aud_como_texto_o_como_lista_son_validas(idp):
    validator = _validator(idp)[0]
    assert validator.validate(idp.token(aud=AUDIENCE))
    assert validator.validate(idp.token(aud=["otro", AUDIENCE]))


# ---------------------------------------------------------------- criterio de la fase 1
def test_token_expirado_se_rechaza(idp):
    _rechazado(_validator(idp)[0], idp.token(exp=int(time.time()) - 3600), "ExpiredSignatureError")


def test_aud_incorrecta_se_rechaza(idp):
    validator = _validator(idp)[0]
    _rechazado(validator, idp.token(aud="otro-servicio"), "InvalidAudienceError")
    _rechazado(validator, idp.token(aud=["account"]), "InvalidAudienceError")
    _rechazado(validator, idp.token(aud=None), "MissingRequiredClaimError")


def test_emisor_distinto_se_rechaza(idp):
    _rechazado(_validator(idp)[0], idp.token(iss="http://otro/realms/acxes"), "InvalidIssuerError")


def test_nbf_en_el_futuro_se_rechaza(idp):
    _rechazado(_validator(idp)[0], idp.token(nbf=int(time.time()) + 3600), "ImmatureSignatureError")


def test_iat_en_el_futuro_se_rechaza(idp):
    _rechazado(_validator(idp)[0], idp.token(iat=int(time.time()) + 3600), "ImmatureSignatureError")


@pytest.mark.parametrize("faltante", ["exp", "iat", "iss", "sub"])
def test_claims_obligatorios(idp, faltante):
    _rechazado(_validator(idp)[0], idp.token(**{faltante: None}), "MissingRequiredClaimError")


def test_azp_distinto_o_ausente_se_rechaza(idp):
    validator = _validator(idp)[0]
    _rechazado(validator, idp.token(azp="otro-cliente"), "azp")
    _rechazado(validator, idp.token(azp=None), "azp")


def test_solo_se_aceptan_access_tokens(idp):
    validator = _validator(idp)[0]
    _rechazado(validator, idp.token(typ="ID"), "typ")
    _rechazado(validator, idp.token(typ="Refresh"), "typ")
    _rechazado(validator, idp.token(typ=None), "typ")


# ---------------------------------------------------------------- ataques clásicos
def test_alg_none_se_rechaza(idp):
    sin_firma = f"{_b64({'alg': 'none', 'typ': 'JWT', 'kid': idp.kid})}.{_b64(_payload())}."
    _rechazado(_validator(idp)[0], sin_firma, "alg")


def test_confusion_rs256_hs256_se_rechaza(idp):
    """Firmar con HS256 usando la clave pública como secreto no debe validar."""
    pem = idp.private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    head = _b64({"alg": "HS256", "typ": "JWT", "kid": idp.kid})
    body = _b64(_payload())
    sig = hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest()
    token = f"{head}.{body}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"
    _rechazado(_validator(idp)[0], token, "alg")


def test_firma_de_otra_clave_con_el_mismo_kid_se_rechaza(idp):
    impostor = Idp(kid=idp.kid)
    _rechazado(_validator(idp)[0], impostor.token(), "InvalidSignatureError")


def test_payload_alterado_se_rechaza(idp):
    head, _body, sig = idp.token().split(".")
    forjado = _b64(_payload(sub="otra-persona"))
    _rechazado(_validator(idp)[0], f"{head}.{forjado}.{sig}", "InvalidSignatureError")


@pytest.mark.parametrize("basura", ["", "abc", "a.b.c", "x" * (MAX_TOKEN_CHARS + 1)])
def test_tokens_mal_formados_o_enormes(idp, basura):
    _rechazado(_validator(idp)[0], basura)


def test_sin_kid_se_rechaza(idp):
    sin_kid = jwt.encode({"sub": USER}, idp.private, algorithm="RS256")
    _rechazado(_validator(idp)[0], sin_kid, "kid")


# ---------------------------------------------------------------- JWKS: caché y rotación
def test_si_el_jwks_no_responde_se_deniega(idp):
    def caido():
        raise ConnectionError("keycloak caído")

    _rechazado(_validator(idp, jwks=caido)[0], idp.token(), "jwks_unavailable")


def test_el_jwks_se_cachea(idp):
    validator, fetches = _validator(idp)
    for _ in range(5):
        validator.validate(idp.token())
    assert len(fetches) == 1


def test_rotacion_de_claves_con_kid_nuevo():
    clock = Clock()
    viejo, nuevo = Idp("k1"), Idp("k2")
    publicadas = [viejo]
    validator, fetches = _validator(
        viejo, jwks=lambda: {"keys": [i.jwk() for i in publicadas]}, clock=clock, min_refresh_s=30
    )
    assert validator.validate(viejo.token())

    publicadas.append(nuevo)  # Keycloak rota y publica la clave nueva
    _rechazado(validator, nuevo.token(), "unknown_kid")  # aún dentro del intervalo mínimo
    clock.now += 31
    assert validator.validate(nuevo.token())
    assert len(fetches) == 2


def test_kid_desconocido_no_puede_forzar_peticiones_a_keycloak(idp):
    """Sin intervalo mínimo, un flujo de tokens falsos sería un amplificador contra Keycloak."""
    clock = Clock()
    validator, fetches = _validator(idp, clock=clock, min_refresh_s=30)
    validator.validate(idp.token())
    desconocida = Idp("kid-falso")
    for _ in range(50):
        _rechazado(validator, desconocida.token(), "unknown_kid")
    assert len(fetches) == 1
