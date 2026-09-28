# Front de ACXES

Interfaz web del asistente. Es un **monolito**: el mismo proceso FastAPI sirve el front
(`acxes/web/`) y la API (`acxes/edge_api/app.py`). No hay Node, ni paso de compilación,
ni dependencias de JavaScript: HTML, CSS y módulos ES nativos.

Identidad visual: granate `#A50044`, el rojo de la camiseta blaugrana, con azul `#004D98`
y dorado `#EDBB00` como acentos (el dorado marca las etiquetas ACL).

## Cómo correrlo

```
pip install -e ".[dev]"
uvicorn acxes.edge_api.app:app --reload --port 8000
```

Abrir <http://localhost:8000>. Sin más configuración arranca en **modo demo**
(`ACXES_FRONT_DEMO=1`): no necesita Docker, ni Keycloak, ni Postgres, ni clave de Groq.
En Windows (cmd) las variables se declaran con `set`, por ejemplo `set ACXES_FRONT_DEMO=0`.

| Variable | Por defecto | Uso |
|---|---|---|
| `ACXES_FRONT_DEMO` | `1` | `1` = motor de demo. `0` = API real (hoy responde 501 en `/api/me` y `/api/chat`). |
| `KEYCLOAK_PUBLIC_URL` | `http://localhost:8080` | URL de Keycloak vista desde el navegador. |
| `KEYCLOAK_PORT` | `8080` | Solo para armar la URL anterior. |
| `KEYCLOAK_REALM` | `acxes` | Realm. |
| `KEYCLOAK_WEB_CLIENT_ID` | `acxes-chat-web` | Client público del front. |

## Estructura

```
acxes/web/
├── index.html                # login + app (una sola página)
└── assets/
    ├── css/tokens.css        # colores, radios, sombras
    ├── css/app.css           # estilos
    ├── img/logo.svg          # marca ACXES (escudo con X)
    └── js/
        ├── main.js           # arranque, vistas, flujo del chat
        ├── auth.js           # Keycloak: Authorization Code + PKCE, refresh, logout, demo
        ├── api.js            # fetch con Bearer, renovación ante 401
        ├── ui.js             # render: mensajes, fuentes, traza del AI Gateway, alcance
        └── store.js          # historial por usuario y versión de política (P15)
acxes/edge_api/
├── app.py                    # FastAPI: sirve el front y expone /api/*
└── demo_engine.py            # SUSTITUTO de desarrollo. Se reemplaza por la API real
```

## Qué hace cada pantalla

**Login.** Un solo botón, *Continuar con Keycloak*, que inicia Authorization Code + PKCE
(S256). La contraseña se escribe únicamente en Keycloak; el front nunca la ve. Al volver con
`?code=`, el front intercambia el código con el `code_verifier` y guarda los tokens.
En modo demo aparecen además los seis usuarios de prueba.

**Chat.** Solo se entra con sesión. Cada respuesta muestra:

- las **fuentes** citadas, cada una con su nivel de sensibilidad, dependencia y etiquetas ACL;
- la **traza del AI Gateway** (desplegable): identidad → SecurityContext → predicado del PDP →
  Tool Gateway → recuperación con RLS → guardia de salida, con latencia y tokens;
- un mensaje de denegación **único** cuando no hay fuentes autorizadas (P12 y P17), sin
  distinguir entre "no existe" y "no tienes permiso".

El panel **Mi alcance** muestra qué dependencias, niveles y etiquetas tiene el perfil. Es
informativo: la decisión real siempre la toma el PDP en el servidor.

## Contrato de la API

El cuerpo de `/api/chat` solo admite `message` y `conversation_id` (`extra="forbid"`): el
cliente no puede enviar rol, dependencia ni nivel. La identidad sale únicamente del token.

| Método y ruta | Auth | Respuesta |
|---|---|---|
| `GET /api/config` | no | `{demo, keycloak:{url,realm,clientId}, policy_version, demo_users[]}` |
| `POST /api/demo/login` | no (solo demo) | `{access_token, expires_in, token_type}` |
| `GET /api/me` | Bearer | `{user_id, full_name, roles[], dept, clearance, acl_tags[], policy_version}` |
| `POST /api/chat` | Bearer | ver abajo |

Errores que el front maneja: `401` (renueva el token una vez y, si falla, vuelve al login),
`429` (P13, 30 solicitudes por minuto), `501` (API real pendiente), `0` (sin conexión).

```jsonc
// POST /api/chat  ->  200
{
  "answer": "texto de la respuesta (admite **negrita** y párrafos)",
  "citations": [
    { "chunk_id": "…", "doc_id": "…", "title": "…", "dept": "financiera",
      "sensitivity": "confidencial", "acl_tags": [] }
  ],
  "gateway": {
    "engine": "demo",                       // en la API real se omite
    "policy_version": "2026-09-01.1",
    "decision": "allow",                    // "allow" | "deny"
    "predicate": { "allowed_depts": ["institucional","financiera"], "max_sensitivity": "confidencial",
                   "owner_id": "…", "acl_tags": ["auditoria_interna"] },     // null si se rechazó la identidad
    "tool_calls": [ { "name": "buscar_documentos", "args": {"keywords": ["…"]}, "result": "ok", "chunks": 3 } ],
    "output_guard": "passed",               // "passed" | "redacted" | "blocked"
    "iterations": 1, "prompt_tokens": 0, "completion_tokens": 0, "latency_s": 0.02
  }
}
```

`gateway` sale de datos que ya existen: `predicate` es el que entrega el PDP (`allowed_depts`,
`max_sensitivity`, `owner_id`, `acl_tags`) y `tool_calls` / tokens / latencia / iteraciones
salen del `TurnResult` de `acxes/orchestrator/turn.py`.

## Contrato con Keycloak

El borrador `keycloak/acxes-realm.json.draft` define lo que el front espera. Para usarlo,
renombrarlo a `acxes-realm.json` y reiniciar Keycloak (`docker-compose.yml` ya monta `./keycloak`
con `--import-realm`).

**No pude probarlo en este entorno (sin Docker).** Si Keycloak falla al importarlo, quitar el
archivo y crear a mano lo siguiente en la consola de administración:

| Elemento | Valor |
|---|---|
| Realm | `acxes` |
| Roles de realm | `empleado`, `supervisor`, `administrador` |
| Client del front | `acxes-chat-web`, público, Standard Flow, Direct Access Grants **desactivado**, PKCE `S256` |
| Redirect URIs / Web origins | `http://localhost:8000/*` y `http://localhost:8000` |
| Mappers (access token) | atributo `dept`, atributo `clearance`, atributo multivalor `acl_tags`, audiencia `acxes-chat-api` |
| Usuarios | los seis de `acxes/db/seed.sql`, con el **mismo UUID** como id de usuario de Keycloak |
| Usuarios de prueba | contraseña `acxes123` (solo desarrollo) |

Claims que la API de borde debe leer: `sub`, `realm_access.roles`, `dept`, `clearance`,
`acl_tags`, `aud`. Keycloak ya emite `sid`; se puede mapear a `session_id`. El nombre del usuario
**no** va en el token (sin PII): sale de `/api/me`.

## Lo que falta conectar (reemplazar `demo_engine`)

Marcado en el código como `TODO(etapa N)`. El front no cambia.

| Pieza real | Sustituye a | Etapa |
|---|---|---|
| Validar el JWT (RS256 contra el JWKS, `iss`, `aud`, `exp`, `nbf`, `azp`) y construir el `SecurityContext` | `verify_demo_token` y `_require_claims` en `app.py` | 2 |
| `acxes/pdp/` con la regla de `POLITICAS_ACCESO.md` | `build_predicate` e `is_visible` en `demo_engine.py` | 3 |
| `acxes/tool_gateway/` + retrieval con RLS | la búsqueda del demo | 3–4 |
| Orquestador S con `LLMClient` (Groq) | la plantilla de respuesta del demo | 4 |
| `acxes/output_guard/` | el campo `output_guard` (hoy siempre `passed`) | 5 |
| Rate limit real y auditoría | `rate_limited` | 5 |

`tests/unit/test_demo_engine.py` fija la regla de visibilidad (P1 a P8 y P12) sobre el corpus
real. Cuando exista el PDP, las mismas pruebas deben pasar contra él.

## Decisiones y límites conocidos

- **Tokens en `sessionStorage`** (por pestaña, se borran al cerrarla). Es un compromiso de
  desarrollo: un script inyectado podría leerlos. Todo el contenido dinámico se inserta como
  texto (nunca `innerHTML`) para reducir ese riesgo. Un despliegue real debería usar el patrón
  BFF con cookie `HttpOnly`.
- **El front no valida la firma del JWT.** Solo decodifica el payload para mostrar datos. La
  validación es responsabilidad de la API de borde, en cada request (`docs/ARQUITECTURA.md`, 4.2).
- **Sin streaming** de la respuesta del modelo. Se puede añadir con SSE sin cambiar la traza.
- **Sin cierre global (back-channel logout)**, descartado en la arquitectura.
- El historial es local a la pestaña y se descarta si cambia `policy_version` (P15).
