# Conexión front ↔ back

El front (`acxes/web`) habla con una sola API (`acxes/edge_api/app.py`). El modo se elige con `ACXES_MODE` en `.env`.

| Modo | Qué corre | Necesita |
|---|---|---|
| `demo` | Motor de prueba con plantillas. **No** es la arquitectura Secure | Nada |
| `dev` | Agente S real: PDP, Tool Gateway, RLS, `LLM_CLIENT`. Sesiones de prueba sin Keycloak | PostgreSQL con `python -m acxes.db.apply` |
| `keycloak` | Lo mismo que `dev`, pero con login OIDC + PKCE y tokens RS256 validados | PostgreSQL + Keycloak con el realm importado |

## Ruta de una pregunta (modos `dev` y `keycloak`)

1. `POST /api/chat` con `Authorization: Bearer <JWT>` y cuerpo `{message, conversation_id}`. El cuerpo no admite rol ni identidad.
2. `jwt_validator.py` comprueba firma RS256 contra el JWKS, `iss`, `aud`, `exp`, `nbf`, `azp` y `typ=Bearer`. Rechaza `alg: none` y HS256.
3. `service.py` construye el `SecurityContext` con la versión de política del PDP.
4. `SecureAgent.respond` → Tool Gateway → PDP → recuperación con RLS.
5. `presenter.py` convierte el resultado al JSON que pinta el front. No expone el motivo de una denegación (P14).

Errores siempre genéricos: 401 token, 403 sin acceso, 429 límite, 503 falla de infraestructura. El detalle queda en el log del servidor.

## Archivos

Nuevos: `acxes/edge_api/{errors,ratelimit,jwt_validator,service,presenter}.py`, `.env.example`.
Editados: `acxes/config.py`, `acxes/secure_app.py`, `acxes/retrieval/{secure,types}.py`, `acxes/edge_api/{app,demo_engine}.py`, `acxes/web/assets/js/{ui,main}.js`, `.gitignore`.
Pruebas: `tests/unit/test_jwt_validator.py`, `tests/integration/test_edge_api_secure.py`, `tests/unit/test_demo_engine.py`.

## Pendiente

- Guardia de salida (etapa 5): el front muestra `output_guard: pending` y no afirma que se aplicó.
- Keycloak: renombrar `keycloak/acxes-realm.json.draft` a `acxes-realm.json` para que `docker compose` lo importe, y verificar el login con una cuenta real (no se probó con un Keycloak real).
- Los tokens viven en `sessionStorage`. Para producción lo correcto es un BFF con cookie HttpOnly.
