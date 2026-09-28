"""Motor de DEMO para desarrollar el front antes de que existan la API de borde real,
el PDP y el Tool Gateway (etapas 2 a 4 de `docs/ARQUITECTURA.md`).

NO es el sistema Secure. Es un sustituto de desarrollo que:

* emite tokens de demo firmados con HMAC (no son JWT de Keycloak y solo los acepta este
  proceso);
* aplica la regla de visibilidad de `documents/POLITICAS_ACCESO.md` (tres condiciones,
  P1 a P7) sobre el corpus real de `data/corpus/`, *antes* de buscar, igual que hará el PDP;
* redacta la respuesta con una plantilla, sin ningún modelo de lenguaje.

Cuando exista la API de borde real, se reemplaza `demo_engine` por: validación del JWT
contra el JWKS de Keycloak -> SecurityContext -> orquestador S -> Tool Gateway + PDP ->
guardia de salida. El contrato JSON que consume el front no cambia.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "data" / "corpus"

POLICY_VERSION = "2026-09-01.1"
LEVELS = ("publico", "interno", "confidencial", "restringido")
DEPTS = ("institucional", "academica", "financiera")
MAX_BY_ROLE = {"empleado": "interno", "supervisor": "confidencial", "administrador": "confidencial"}
RATE_LIMIT_PER_MIN = 30  # P13
K = 5  # P13
DENIAL = "No encontré información disponible para tu perfil sobre esa consulta."  # P12/P17


def _lvl(name: str) -> int:
    return LEVELS.index(name)


# --------------------------------------------------------------------------- usuarios
@dataclass(frozen=True)
class DemoUser:
    id: str
    full_name: str
    role: str
    dept: str
    clearance: str
    acl_tags: tuple[str, ...]


# Espejo de acxes/db/seed.sql (los seis usuarios de prueba)
DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("00000000-0000-4000-a000-000000000001", "Sofía Ariza", "empleado", "financiera", "interno", ()),
    DemoUser("00000000-0000-4000-a000-000000000002", "Belén Quintero", "empleado", "financiera", "interno", ()),
    DemoUser("00000000-0000-4000-a000-000000000003", "Ángela Gómez", "empleado", "academica", "interno", ()),
    DemoUser("00000000-0000-4000-a000-000000000004", "Laura Martínez", "supervisor", "financiera", "confidencial", ("auditoria_interna",)),
    DemoUser("00000000-0000-4000-a000-000000000005", "Carlos Rentería", "supervisor", "academica", "confidencial", ("comite_disciplinario",)),
    DemoUser("00000000-0000-4000-a000-000000000006", "Diego Fajardo", "administrador", "institucional", "confidencial", ()),
)
_BY_ID = {u.id: u for u in DEMO_USERS}
_BY_NAME = {u.full_name: u for u in DEMO_USERS}


# --------------------------------------------------------------------------- tokens demo
_SECRET = secrets.token_bytes(32)  # se regenera en cada arranque


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_demo_token(user: DemoUser, ttl_s: int = 900) -> dict:
    now = int(time.time())
    claims = {
        "sub": user.id,
        "realm_access": {"roles": [user.role]},
        "dept": user.dept,
        "clearance": user.clearance,
        "acl_tags": list(user.acl_tags),
        "session_id": secrets.token_hex(8),
        "iss": "acxes-demo",
        "aud": "acxes-chat-api",
        "iat": now,
        "exp": now + ttl_s,
    }
    head = _b64(json.dumps({"alg": "HS256", "typ": "demo"}).encode())
    body = _b64(json.dumps(claims).encode())
    sig = _b64(hmac.new(_SECRET, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return {"access_token": f"{head}.{body}.{sig}", "expires_in": ttl_s, "token_type": "Bearer"}


def verify_demo_token(token: str) -> dict | None:
    """Devuelve los claims si el token de demo es válido y no expiró; si no, None."""
    try:
        head, body, sig = token.split(".")
        expected = _b64(hmac.new(_SECRET, f"{head}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("exp", 0) < time.time() or claims.get("aud") != "acxes-chat-api":
        return None
    return claims


# --------------------------------------------------------------------------- PDP de demo
@dataclass(frozen=True)
class Predicate:
    allowed_depts: tuple[str, ...]
    max_sensitivity: str
    owner_id: str
    acl_tags: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "allowed_depts": list(self.allowed_depts),
            "max_sensitivity": self.max_sensitivity,
            "owner_id": self.owner_id,
            "acl_tags": list(self.acl_tags),
        }


class Denied(Exception):
    """Denegación por identidad inválida (P7, P8, P9, P14). El detalle no sale al usuario."""


def build_predicate(claims: dict) -> Predicate:
    roles = [r for r in claims.get("realm_access", {}).get("roles", []) if r in MAX_BY_ROLE]
    if len(roles) != 1:  # P8
        raise Denied("roles")
    role = roles[0]
    dept = claims.get("dept")
    if dept not in DEPTS:  # P9
        raise Denied("dept")
    if claims.get("clearance") != MAX_BY_ROLE[role]:  # P7
        raise Denied("clearance")
    depts = DEPTS if role == "administrador" else tuple(dict.fromkeys(("institucional", dept)))  # P1
    return Predicate(depts, MAX_BY_ROLE[role], claims["sub"], tuple(claims.get("acl_tags", [])))


# --------------------------------------------------------------------------- corpus
@dataclass(frozen=True)
class Doc:
    slug: str
    title: str
    dept: str
    sensitivity: str
    owner_id: str | None
    acl_tags: tuple[str, ...]
    body: str


@lru_cache(maxsize=1)
def load_corpus() -> tuple[Doc, ...]:
    plan = yaml.safe_load((CORPUS_DIR / "plan.yaml").read_text(encoding="utf-8"))["documents"]
    docs: list[Doc] = []
    for entry in plan:
        path = CORPUS_DIR / "docs" / f"{entry['slug']}.json"
        if not path.exists():
            continue
        body = json.loads(path.read_text(encoding="utf-8")).get("body", "")
        owner = _BY_NAME.get(entry.get("owner", ""))
        docs.append(
            Doc(
                entry["slug"], entry["title"], entry["dept"], entry["sensitivity"],
                owner.id if owner else None, tuple(entry.get("acl_tags") or ()), body,
            )
        )
    return tuple(docs)


def is_visible(doc: Doc, p: Predicate) -> bool:
    """La regla de POLITICAS_ACCESO.md: tres condiciones, cualquiera basta."""
    s = _lvl(doc.sensitivity)
    if doc.dept in p.allowed_depts and s <= _lvl(p.max_sensitivity):  # 1
        return True
    if doc.owner_id == p.owner_id and s <= _lvl("confidencial"):  # 2 (P3)
        return True
    return doc.sensitivity == "restringido" and bool(set(doc.acl_tags) & set(p.acl_tags))  # 3 (P4)


# --------------------------------------------------------------------------- búsqueda
_STOP = frozenset(
    {
        "a",
        "al",
        "algo",
        "ante",
        "como",
        "con",
        "cual",
        "cuales",
        "cuando",
        "de",
        "del",
        "el",
        "ella",
        "en",
        "es",
        "esta",
        "este",
        "la",
        "las",
        "lo",
        "los",
        "me",
        "mi",
        "mis",
        "muy",
        "no",
        "o",
        "para",
        "por",
        "que",
        "quien",
        "se",
        "si",
        "sobre",
        "su",
        "sus",
        "un",
        "una",
        "uno",
        "y",
        "ya",
        "hay",
        "dame",
        "dime",
        "necesito",
        "quiero",
        "puedes",
        "puede",
        "muestrame",
        "mostrar",
        "dato",
        "datos",
        "informacion",
    }
)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _norm(text)) if len(t) > 2 and t not in _STOP]


def _excerpt(body: str, limit: int = 340) -> str:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    text = " ".join(lines[1:] if len(lines) > 1 else lines)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


_hits: dict[str, deque] = defaultdict(deque)


def rate_limited(user_id: str) -> bool:
    now = time.time()
    q = _hits[user_id]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        return True
    q.append(now)
    return False


def answer(claims: dict, message: str) -> dict:
    """Ejecuta un turno de demo y devuelve el contrato JSON que consume el front."""
    started = time.perf_counter()
    trace = {
        "engine": "demo",
        "policy_version": POLICY_VERSION,
        "decision": "deny",
        "predicate": None,
        "tool_calls": [],
        "output_guard": "passed",
        "iterations": 1,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    try:
        pred = build_predicate(claims)
    except Denied:
        trace["latency_s"] = round(time.perf_counter() - started, 3)
        return {"answer": DENIAL, "citations": [], "gateway": trace}

    trace["predicate"] = pred.as_dict()
    keywords = list(dict.fromkeys(_tokens(message)))[:8]
    visible = [d for d in load_corpus() if is_visible(d, pred)]  # autorizar ANTES de buscar

    mine = bool(set(re.findall(r"[a-z]+", _norm(message))) & {"mi", "mis", "mio", "mia", "propia", "propio"})
    scored = []
    for d in visible:
        hay = _norm(f"{d.title} {d.title} {d.body}")
        score = sum(hay.count(k) for k in keywords)
        if score:
            if mine and d.owner_id == pred.owner_id:
                score += 1000  # "mi nómina": prioriza el registro propio (P3)
            scored.append((score, d))
    scored.sort(key=lambda t: -t[0])
    top = [d for _, d in scored[:K]]

    trace["tool_calls"] = [
        {
            "name": "buscar_documentos",
            "args": {"keywords": keywords},
            "result": "ok" if top else "sin_resultados",
            "chunks": len(top),
        }
    ]
    if not top:
        trace["latency_s"] = round(time.perf_counter() - started, 3)
        return {"answer": DENIAL, "citations": [], "gateway": trace}

    trace["decision"] = "allow"
    best = top[0]
    text = f"Según **{best.title}**: {_excerpt(best.body)}"
    if len(top) > 1:
        text += "\n\nTambién encontré información relacionada en las fuentes que aparecen abajo."
    citations = [
        {
            "chunk_id": f"{d.slug}#0",
            "doc_id": d.slug,
            "title": d.title,
            "dept": d.dept,
            "sensitivity": d.sensitivity,
            "acl_tags": list(d.acl_tags),
        }
        for d in top
    ]
    trace["latency_s"] = round(time.perf_counter() - started, 3)
    return {"answer": text, "citations": citations, "gateway": trace}


def profile(claims: dict) -> dict:
    user = _BY_ID.get(claims.get("sub", ""))
    roles = [r for r in claims.get("realm_access", {}).get("roles", []) if r in MAX_BY_ROLE]
    return {
        "user_id": claims.get("sub"),
        "full_name": user.full_name if user else "Usuario",
        "roles": roles,
        "dept": claims.get("dept"),
        "clearance": claims.get("clearance"),
        "acl_tags": claims.get("acl_tags", []),
        "policy_version": POLICY_VERSION,
    }
