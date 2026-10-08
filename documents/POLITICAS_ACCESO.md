# Políticas de acceso

Estado: aprobadas por el equipo para la etapa 1. Complementan a `MATRIZ_ACCESO.md`. Si una política cambia, se actualiza este documento y se registra la desviación.

## Regla de visibilidad

La misma regla se implementa en el PDP, como estructura de datos, y en RLS, como SQL. Una fila es visible si se cumple alguna de estas tres condiciones:

1. Su dependencia está en `allowed_depts` y su sensibilidad no supera `max_sensitivity`.
2. Su `owner_id` es el usuario y su sensibilidad no supera `confidencial`.
3. Su sensibilidad es `restringido` y sus `acl_tags` comparten al menos una etiqueta con las del usuario.

El predicado que entrega el PDP contiene `allowed_depts`, `max_sensitivity`, `owner_id` y `acl_tags`. El PDP nunca emite `max_sensitivity = restringido`.

## Políticas

### Acceso a filas

| Id | Política |
|---|---|
| P1 | Empleado y supervisor ven `institucional` y su dependencia. El administrador tiene una lista explícita con las tres dependencias, sin comodín |
| P2 | No hay regla especial para documentos públicos de otras dependencias. Lo público que deba verse desde cualquier dependencia se ubica en `institucional` |
| P3 | El dueño ve sus registros hasta `confidencial`, sin importar su dependencia ni su tope por rol. Nunca `restringido` |
| P4 | `restringido` solo es visible por intersección de etiquetas, sin exigir dependencia. Una fila `restringido` sin etiquetas no la ve nadie |
| P5 | Las etiquetas solo se evalúan en `restringido`. Una restricción `CHECK` impide filas con `acl_tags` no vacío en niveles inferiores |
| P6 | Etiquetas iniciales `comite_disciplinario` (académica) y `auditoria_interna` (financiera). Hay al menos un supervisor por etiqueta, ningún administrador con etiquetas y un empleado sin ninguna |

### Identidad y rol

| Id | Política |
|---|---|
| P7 | El PDP calcula el nivel máximo a partir del rol que el usuario tiene en la base, con una tabla del YAML de políticas. El claim `clearance` del token no se usa para decidir. Redacción de la etapa 3, pendiente de aprobación del equipo |
| P8 | El rol se lee de la base (`user_roles`). Se descartan los roles ajenos al sistema y el usuario debe quedar con exactamente un rol reconocido. Con cero o más de uno se deniega. Redacción de la etapa 3, pendiente de aprobación del equipo |
| P9 | La dependencia se lee de la base. Si no está en el catálogo (`institucional`, `academica`, `financiera`), se deniega |
| P10 | Sin expiración de roles en la versión base. `expires_at` puede existir pero el PDP no lo evalúa. Queda como trabajo futuro |

### Herramientas y límites

| Id | Política |
|---|---|
| P11 | `buscar_documentos` y `leer_documento` están disponibles para los tres roles. La diferencia entre roles la produce el predicado |
| P12 | `leer_documento` pasa por el mismo predicado que la búsqueda. Un documento inexistente y uno no autorizado devuelven la misma respuesta |
| P13 | `k = 5` por configuración, de 3 a 8 palabras clave de hasta 40 caracteres cada una, máximo de 4 iteraciones del modelo por turno y 30 solicitudes por minuto por usuario. Presupuesto de 16000 tokens por turno, sumando entrada y salida de todas las iteraciones, igual en B1 y S. Valor de la etapa 4, pendiente de aprobación del equipo |

### Fallos y ciclo de vida

| Id | Política |
|---|---|
| P14 | Se deniega con mensaje genérico ante error del PDP, tiempo agotado (500 ms), política ausente, `policy_version` no coincidente, variable de sesión ausente y rol o dependencia inválidos. El detalle va solo a la auditoría |
| P15 | La versión de política tiene formato `AAAA-MM-DD.n`. El historial y la caché usan la clave `(user_id, session_id, policy_version)` y se invalidan cuando la versión cambia |

### Auditoría y salida

| Id | Política |
|---|---|
| P16 | El rol de aplicación solo inserta en el registro de auditoría. Nadie lo lee desde la aplicación y la lectura se hace con el rol de auditoría desde un script |
| P17 | Un único mensaje de denegación aplicado por la guardia de salida. Toda afirmación cita un `chunk_id` devuelto en ese turno. Sin recuperación solo se aceptan saludos y aclaraciones sobre el sistema. El detalle se define en la etapa 5 |

## Fuente de verdad y revocación

La base es la fuente de verdad para autorizar. Keycloak autentica y el token identifica al usuario por `sub`. El PDP lee el rol, la dependencia y las etiquetas de `users` y `user_roles` en cada evaluación, mediante la función `pdp_subject` y el rol `acxes_pdp`. Si los claims del token difieren de la base, prevalece la base y la diferencia queda registrada para la auditoría.

Para revocar un permiso se modifica la base con el rol propietario. El cambio surte efecto en la siguiente evaluación, aunque el usuario conserve su token. Después se actualiza el atributo en Keycloak para que los tokens nuevos coincidan.

```sql
-- Quitar una etiqueta
UPDATE users SET acl_tags = array_remove(acl_tags, 'comite_disciplinario') WHERE id = '<uuid>';
-- Cambiar el rol
UPDATE user_roles SET role_id = (SELECT id FROM roles WHERE name = 'empleado') WHERE user_id = '<uuid>';
-- Retirar todo acceso
DELETE FROM user_roles WHERE user_id = '<uuid>';
```

## Clasificación del corpus

| Nivel | Ejemplos | Dependencia típica | `owner_id` | `acl_tags` |
|---|---|---|---|---|
| publico | Reglamento general, calendario, circulares generales, señuelos | institucional | No | Vacío |
| interno | Procedimientos, circulares internas, actas ordinarias, presupuesto resumido | academica, financiera, institucional | No | Vacío |
| confidencial | Nómina individual, evaluación de desempeño, calificaciones, presupuesto detallado | academica, financiera | Sí en nómina y evaluación | Vacío |
| restringido | Actas del comité disciplinario, informes de auditoría interna | academica, financiera | No | Una etiqueta de P6 |

El corpus incluye además documentos públicos con instrucciones de inyección indirecta para la etapa 6 y tokens canario en todo documento confidencial o restringido.

## Resultado esperado por rol

| Rol | Dependencia `institucional` | Dependencia propia | Otras dependencias | Registros propios | Restringido |
|---|---|---|---|---|---|
| empleado | Hasta interno | Hasta interno | Nada | Hasta confidencial | No |
| supervisor | Hasta confidencial | Hasta confidencial | Nada | Hasta confidencial | Solo con etiqueta coincidente |
| administrador | Hasta confidencial | Hasta confidencial | Hasta confidencial | Hasta confidencial | Solo con etiqueta coincidente, sin etiquetas por defecto |
