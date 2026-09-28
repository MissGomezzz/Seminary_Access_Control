# Contrato entre la etapa 2 y la etapa 3

Estado: vigente desde la etapa 3. Describe lo que la API de borde debe entregar para que el PDP y el servicio de recuperación funcionen sin cambios.

## Qué hace cada etapa

La etapa 2 prueba la identidad una sola vez. Valida la firma RS256 del JWT contra el JWKS de Keycloak, revisa `iss`, `aud`, `exp`, `nbf` y `azp`, rechaza `alg: none` y aplica el límite de tasa. Solo con el token ya validado construye el `SecurityContext`.

La etapa 3 decide y filtra. El PDP (`acxes/pdp/evaluator.py`) identifica al usuario por `user_id`, lee su rol, dependencia y etiquetas de la base en cada evaluación, aplica P7, P8, P9, P11 y P14 y devuelve un predicado. El servicio de recuperación (`acxes/retrieval/secure.py`) aplica el predicado en la consulta y en las variables de sesión de RLS.

## Cómo se conecta

```python
from acxes.config import get_settings
from acxes.pdp.evaluator import PolicyDecisionPoint
from acxes.pdp.subject_store import PostgresSubjectStore
from acxes.security_context import SecurityContext

# Una instancia por proceso. Necesita POSTGRES_PDP_PASSWORD en .env
pdp = PolicyDecisionPoint(PostgresSubjectStore(get_settings()))

def construir_contexto(claims_validados: dict) -> SecurityContext:
    if pdp.policy_version is None:
        raise ...  # sin política válida se deniega todo, responder con error genérico
    return SecurityContext.from_claims(claims_validados, policy_version=pdp.policy_version)
```

`from_claims` lanza `ValueError` si falta un claim o tiene un tipo inesperado. La API de borde debe responder entonces con un 401 genérico.

## Claims esperados en el access token

| Claim | Tipo | Uso |
|---|---|---|
| `sub` | UUID en texto | `user_id`. Debe ser el mismo UUID de `acxes/db/seed.sql`, porque la regla de propiedad lo compara con `owner_id`. El borrador del realm ya fija esos identificadores |
| `realm_access.roles` | lista de texto | Informativo. El PDP toma el rol de la base |
| `dept` | texto | Informativo. El PDP toma la dependencia de la base |
| `clearance` | texto | Informativo. El nivel sale del rol de la base |
| `acl_tags` | lista de texto | Informativo. Si Keycloak lo omite porque está vacío, equivale a ninguna etiqueta. El PDP toma las etiquetas de la base |
| `session_id` o `sid` | texto | Keycloak emite `sid`. Se usa para la clave del historial (P15) |

Los claims informativos siguen siendo obligatorios en `from_claims` y sirven para la interfaz. Si difieren de la base, el PDP decide con la base y anota la diferencia en `Decision.claims_drift` para la auditoría. Conviene mantenerlos sincronizados, porque una diferencia persistente indica un mapper mal configurado.

## Qué no debe hacer la API de borde

- Pasar el JWT o cualquier claim al modelo o a las herramientas.
- Decidir permisos por su cuenta ni mostrar los claims como permisos efectivos. El nivel, las dependencias visibles y las etiquetas efectivas salen del PDP, que los lee de la base.
- Mantener una copia propia de la política. `demo_engine.build_predicate`, de la rama `feature/frontend`, repite la regla del PDP. Conviene reemplazarlo por `PolicyDecisionPoint` para que haya una sola implementación en Python, probada contra RLS.

## Cómo probar la integración

`tests/rls/contexts.py` construye los seis contextos de prueba tal como los produciría un token válido. Una prueba de la etapa 2 puede verificar que `from_claims` sobre el token de cada usuario de prueba produce el mismo contexto, salvo `session_id` e `issued_at`.
