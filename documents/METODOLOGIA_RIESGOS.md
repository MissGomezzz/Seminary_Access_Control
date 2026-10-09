# Metodología de gestión de riesgos — ACXE

## 1. Escalas y criterios considerados

### 1.1 Posibilidad y consecuencia

| Valor | Posibilidad | Consecuencia |
|---|---|---|
| **1** | **Baja.** Requiere varias fallas independientes o acceso privilegiado. Sin evidencia en el repositorio | **Menor.** Afecta metadatos o disponibilidad sin exponer contenido. Se corrige sin costo relevante |
| **2** | **Media.** Explotable con esfuerzo moderado, o depende de un control aún pendiente o de una configuración | **Moderada.** Expone o altera uno o pocos documentos, o degrada la integridad de las respuestas |
| **3** | **Alta.** Demostrada en el repositorio, o trivial y sin control implementado | **Grave.** Expone datos confidenciales o restringidos de personas, o permite saltarse el modelo de acceso |

### 1.2 Nivel de riesgo

**Nivel = Posibilidad × Consecuencia**

| Nivel | Clasificación |
|---|---|
| 1 – 2 | 🟩 **Bajo** |
| 3 – 4 | 🟨 **Medio** |
| 6 – 9 | 🟥 **Alto** |

### 1.3 Matriz de referencia

| IMPACTO ↓ / POSIBILIDAD → | Baja (1) | Media (2) | Alta (3) |
|---|---|---|---|
| **Grave (3)** | 🟨 Medio (3) | 🟥 Alto (6) | 🟥 Alto (9) |
| **Moderada (2)** | 🟩 Bajo (2) | 🟨 Medio (4) | 🟥 Alto (6) |
| **Menor (1)** | 🟩 Bajo (1) | 🟩 Bajo (2) | 🟨 Medio (3) |

---

## 2. Identificación: activo, amenaza, vulnerabilidad y CID

| ID | Activo | Amenaza | Vulnerabilidad (evidencia en el repositorio) | CID |
|---|---|---|---|---|
| **R01** | Corpus confidencial y restringido servido por B1 (nómina, evaluaciones, actas disciplinarias, auditorías) | Usuario que consulta datos que no le corresponden | B1 no tiene autorización: la única protección es el prompt, la recuperación no filtra y la conexión usa `acxes_owner` (superusuario, ignora RLS). Demostrado en T01, T03 y T05 (`BASELINE_UNSECURE.md`) | **C** |
| **R02** | Modelo de acceso de S (roles, dependencias, niveles, etiquetas ACL) | Usuario que intenta, desde el chat, hacerse pasar por otro rol o ampliar su alcance ("ignora las instrucciones", "actúa como administrador") | El LLM es no confiable. El Tool Gateway y la guardia de salida están pendientes y `tests/red_team/` está vacío | **C, I** |
| **R03** | Respuestas del asistente y documentos públicos del corpus | Autor de un documento con instrucciones ocultas (inyección indirecta) | 8 documentos públicos llevan cargas en `data/corpus/injections.yaml`: instrucción oculta, falso mensaje del sistema, exfiltración por imagen de Markdown, codificación en base64. No hay guardia de salida que filtre imágenes, enlaces o fuentes no autorizadas | **C, I** |
| **R04** | Identidad y sesión del usuario (API de borde y front) | Suplantación de identidad o acceso sin autenticación real | `ACXES_FRONT_DEMO=1` por defecto. `/api/demo/login` emite un token solo con el `user_id`, sin contraseña. La validación del JWT de Keycloak está pendiente (`TODO(etapa 2)` en `app.py`) | **C, I** |
| **R05** | Roles, dependencias y etiquetas (`users`, `user_roles`, claims de Keycloak) | Error humano o abuso de privilegios administrativos, permisos que no se retiran | Sin expiración de roles (P10). La revocación es por SQL manual. Los claims del token pueden diferir de la base (`claims_drift`). El UUID debe coincidir entre Keycloak y `seed.sql`. No existe recertificación periódica implementada | **C, I** |
| **R06** | Base PostgreSQL (`documents`, `chunks`, `users`, `audit_log`) | Acceso directo con credencial amplia, o bug que omita el filtro | `acxes_owner` es superusuario local e ignora RLS. Las claves viven en `.env`. La conexión usa `sslmode=disable`. Si S usara el rol equivocado, RLS sería decorativa | **C, I** |
| **R07** | Secretos: clave de Groq, contraseñas de PostgreSQL, administrador de Keycloak, usuarios de prueba | Atacante externo o integrante del equipo que obtiene credenciales | El README remite a `.env.example` con claves de ejemplo que "deben cambiarse". Contraseña de prueba `acxes123` en el realm de desarrollo. La carpeta `.idea/` está versionada. Riesgo de commit accidental de `.env` | **C, I, D** |
| **R08** | Tokens de sesión y tráfico entre navegador, API, Keycloak y base | Interceptación, XSS o robo de token | Tokens en `sessionStorage` (legibles por un script inyectado). HTTP local, Keycloak en `start-dev` y `sslmode=disable` | **C, I** |
| **R09** | Clasificación del corpus (dependencia, sensibilidad, dueño, etiquetas) y pipeline de ingesta | Error o manipulación de la clasificación al ingerir | El catálogo se escribe a mano (`build_plan.py`). La revisión manual de la muestra del 20 % está pendiente (`REVISION.md` sin marcar). 116 documentos no alcanzan la extensión mínima, 11 incluyen correos y 3 direcciones web | **C, I** |
| **R10** | Información agregada del corpus y volumen de consulta por usuario | Usuario autorizado que combina fragmentos o consulta repetidamente para inferir o reconstruir información más sensible | La regla de agregación (*inference control*) no está definida (`ARQUITECTURA.md`, sección 11). La prueba T06 está pendiente. Las alertas están descartadas. El límite de tasa existe solo en el motor demo | **C** |
| **R11** | Mensajes de denegación y errores de la API | Sondeo para enumerar documentos existentes (oráculo de existencia o de tiempo) | Guardia de salida pendiente. La API devuelve errores con textos distintos (401, 404, 429, 501). No se ha medido la latencia por ruta | **C** |
| **R12** | Disponibilidad del asistente (Groq, Keycloak, PDP, PostgreSQL) | Caída o degradación de un componente o proveedor | Dependencia de un proveedor externo de LLM. La política fail-closed (P14) deniega todo si falla el PDP o la base, con tiempo límite de 500 ms | **D** |
| **R13** | Cuota y costo del proveedor de LLM y capacidad del servicio | Uso abusivo (consultas en bucle) o denegación de servicio por consumo | El límite de tasa real (P13, 30 por minuto) solo existe en demo. El presupuesto de tokens por turno no está definido (etapa 4). El tope de gasto se configura a mano en la consola del proveedor | **D** |
| **R14** | Fragmentos confidenciales enviados como contexto al LLM externo (Groq) | Retención, acceso o uso indebido por el proveedor | Los fragmentos autorizados salen de la institución hacia un tercero. No hay acuerdo de tratamiento de datos evaluado. Los requisitos de habeas data se mencionan en `ARQUITECTURA.md` (sección 11) sin evaluar | **C** |
| **R15** | Registro de auditoría (`audit_log`) | Manipulación, borrado o acceso indebido al registro, o falta de trazabilidad | La auditoría real está pendiente (etapa 5). El propietario (superusuario) puede alterar la tabla. El registro guardará consultas y respuestas, que pueden contener datos sensibles, con retención sin definir | **I, C** |
| **R16** | Motor de decisión PDP y política RLS | Fallo de lógica o desalineación entre PDP (Python) y RLS (SQL), o política mal versionada | La misma regla está en dos implementaciones. P7 y P8 están pendientes de aprobación. `demo_engine.build_predicate` duplica la regla. Existen mitigantes: prueba de equivalencia PDP–RLS y fail-closed en tres capas | **C, I** |
| **R17** | Corpus sintético generado por un LLM | Aparición de datos que parezcan reales (personas, correos, direcciones) | 11 cuerpos con correo y 3 con dirección web. Revisión manual pendiente | **C** |

---

## 3. Escenarios de riesgo

| ID | Escenario |
|---|---|
| **R01** | **Debido a** que la arquitectura B1 delega en el prompt toda la autorización y se conecta a la base con una credencial que ignora RLS, **podría presentarse** que cualquier usuario obtenga documentos que no le corresponden, **afectando** la confidencialidad del corpus confidencial y restringido y **generando** exposición de datos personales y laborales, incumplimiento de la política de acceso y pérdida de credibilidad si B1 se usara fuera del laboratorio |
| **R02** | **Debido a** que el modelo puede ser persuadido por instrucciones del usuario y los controles de S (Tool Gateway y guardia de salida) aún no están completos, **podría presentarse** que un usuario logre que el asistente trate su solicitud con un rol o alcance mayor, **afectando** el modelo de acceso por roles y las fuentes confidenciales y **generando** acceso a información fuera de su nivel y el incumplimiento del criterio de aceptación del proyecto |
| **R03** | **Debido a** que el corpus público contiene documentos con instrucciones ocultas dirigidas al asistente, **podría presentarse** que el modelo las obedezca (por ejemplo, emitir una imagen de Markdown con datos o revelar su prompt), **afectando** la integridad de las respuestas y la confidencialidad de los fragmentos autorizados y **generando** exfiltración hacia un dominio externo o respuestas manipuladas |
| **R04** | **Debido a** que la API de borde funciona en modo demo y aún no valida el JWT de Keycloak, **podría presentarse** que alguien obtenga un token de cualquier usuario sin contraseña, **afectando** la autenticación y la trazabilidad y **generando** acceso con los privilegios de la víctima (incluido el administrador) y registros atribuidos a la persona equivocada |
| **R05** | **Debido a** que los roles no expiran y la revocación se hace por SQL manual, **podría presentarse** que un usuario conserve permisos tras un cambio de cargo o una baja, o que los claims del token y la base queden desalineados, **afectando** la separación de funciones y el mínimo privilegio y **generando** acceso indebido persistente o denegaciones incorrectas |
| **R06** | **Debido a** que el rol propietario es superusuario y las claves viven en `.env` sin TLS, **podría presentarse** que un componente o una persona consulte la base saltándose RLS (o que S use por error el rol equivocado), **afectando** la confidencialidad y la integridad de documentos, fragmentos y usuarios y **generando** fuga masiva o alteración de la clasificación |
| **R07** | **Debido a** que existen claves de ejemplo, contraseñas de prueba y secretos en archivos locales, **podría presentarse** que se filtren al repositorio o se reutilicen (por ejemplo, la clave de Groq o la contraseña del propietario de la base), **afectando** los servicios de LLM, base de datos y Keycloak y **generando** acceso no autorizado, consumo fraudulento y necesidad de rotar credenciales |
| **R08** | **Debido a** que los tokens se guardan en `sessionStorage` y los canales locales no usan TLS, **podría presentarse** el robo o la interceptación de un token de sesión, **afectando** la sesión del usuario y los datos que consulta y **generando** suplantación temporal con los permisos de la víctima |
| **R09** | **Debido a** que la clasificación del corpus depende de un catálogo manual cuya revisión está pendiente, **podría presentarse** que un documento confidencial o restringido quede con un nivel, dependencia o etiqueta incorrectos, **afectando** la regla de visibilidad aplicada por PDP y RLS y **generando** que lo vean usuarios no autorizados (o que nadie lo vea) |
| **R10** | **Debido a** que no está definida la regla de agregación ni existen alertas, **podría presentarse** que un usuario reconstruya información sensible combinando fragmentos permitidos o mediante muchas consultas, **afectando** la confidencialidad de la información inferida y **generando** una fuga parcial que los controles por fila no detectan |
| **R11** | **Debido a** que los mensajes de error y los tiempos de respuesta no son uniformes, **podría presentarse** que un usuario deduzca qué documentos existen aunque no pueda leerlos, **afectando** la confidencialidad de los metadatos y **generando** un oráculo de existencia que facilite ataques posteriores |
| **R12** | **Debido a** la dependencia de Groq, Keycloak, PostgreSQL y el PDP y a la política de denegar ante fallos (P14), **podría presentarse** que el asistente deje de responder o deniegue todo, **afectando** la disponibilidad del servicio y **generando** una interrupción temporal de las consultas, sin pérdida de datos |
| **R13** | **Debido a** que el límite de tasa real y el presupuesto de tokens aún no existen, **podría presentarse** que un usuario agote la cuota o el gasto del proveedor con consultas repetidas, **afectando** la disponibilidad y el presupuesto del proyecto y **generando** caída del servicio y costos no previstos |
| **R14** | **Debido a** que los fragmentos autorizados se envían a un proveedor externo sin un acuerdo de tratamiento de datos evaluado, **podría presentarse** que información confidencial sea retenida, expuesta o usada por el tercero, **afectando** la confidencialidad de datos personales y laborales y **generando** incumplimiento de las normas de protección de datos personales (habeas data) y pérdida de control sobre la información |
| **R15** | **Debido a** que la auditoría está pendiente, el propietario puede modificar la tabla y el registro almacenará consultas y respuestas, **podría presentarse** que no se pueda reconstruir un incidente o que el propio registro exponga contenido sensible, **afectando** la trazabilidad y la confidencialidad de los registros y **generando** incapacidad de investigar fugas y repudio de acciones |
| **R16** | **Debido a** que la misma regla de visibilidad está implementada en dos lugares (PDP en Python y RLS en SQL) y algunas políticas siguen sin aprobar, **podría presentarse** una desalineación o un error de lógica, **afectando** la decisión de acceso y **generando** sobreexposición de documentos o denegaciones falsas por encima del umbral del 15 % |
| **R17** | **Debido a** que el corpus lo redacta un LLM y su revisión manual está pendiente, **podría presentarse** que queden datos que parezcan reales (correos, direcciones, nombres), **afectando** la condición de corpus totalmente ficticio y **generando** una exposición menor y trabajo de regeneración de documentos |

---

## 4. Valoración del riesgo inherente y matriz

| ID | Riesgo | Posibilidad (1–3) | Consecuencia (1–3) | Nivel (P × C) | Clasificación |
|---|---|---|---|---|---|
| **R01** | Fuga por B1 sin autorización | **3** — demostrada en T01, T03 y T05 | **3** — datos confidenciales y restringidos | **9** | 🟥 Alto |
| **R02** | Inyección de prompt directa contra S | **2** — controles de S incompletos | **3** — ampliación de alcance | **6** | 🟥 Alto |
| **R03** | Inyección de prompt indirecta | **2** — cargas ya presentes, efecto depende del modelo | **2** — S solo entrega fragmentos autorizados | **4** | 🟨 Medio |
| **R04** | Suplantación por autenticación pendiente y modo demo | **2** — requiere exponer el modo demo | **3** — acceso con cualquier rol | **6** | 🟥 Alto |
| **R05** | Roles desincronizados y revocación manual | **2** — proceso manual | **2** — acceso indebido acotado | **4** | 🟨 Medio |
| **R06** | Sobreprivilegio en base de datos o bypass de RLS | **2** — depende de configuración | **3** — lectura amplia de la base | **6** | 🟥 Alto |
| **R07** | Secretos y credenciales por defecto | **2** — práctica común en equipos | **3** — acceso a base y proveedor | **6** | 🟥 Alto |
| **R08** | Tokens y tráfico sin cifrado | **2** — requiere XSS o posición en red | **2** — suplantación con ventana corta | **4** | 🟨 Medio |
| **R09** | Error de clasificación en la ingesta | **2** — revisión manual pendiente | **2** — afecta pocos documentos | **4** | 🟨 Medio |
| **R10** | Agregación y exfiltración incremental | **2** — sin regla de agregación | **2** — información inferida | **4** | 🟨 Medio |
| **R11** | Oráculo de existencia y errores | **2** — guardia de salida pendiente | **1** — solo revela existencia | **2** | 🟩 Bajo |
| **R12** | Indisponibilidad de dependencias | **2** — proveedor externo | **1** — consulta no crítica, sin pérdida de datos | **2** | 🟩 Bajo |
| **R13** | Abuso de cuota y costo | **3** — sin límite de tasa real | **1** — tope de gasto en consola | **3** | 🟨 Medio |
| **R14** | Datos confidenciales al proveedor externo | **2** — sin acuerdo evaluado | **3** — datos personales y laborales | **6** | 🟥 Alto |
| **R15** | Auditoría ausente o manipulable | **2** — pendiente y alterable por el propietario | **2** — afecta investigación | **4** | 🟨 Medio |
| **R16** | Fallo de lógica PDP–RLS | **1** — pruebas de equivalencia y tres capas | **3** — decisión de acceso | **3** | 🟨 Medio |
| **R17** | Datos que parecen reales en el corpus | **1** — mayoría de cuerpos revisables | **1** — corpus ficticio, regenerable | **1** | 🟩 Bajo |

**Resumen:** 🟥 6 riesgos altos (R01, R02, R04, R06, R07, R14) · 🟨 8 medios (R03, R05, R08, R09, R10, R13, R15, R16) · 🟩 3 bajos (R11, R12, R17).

### 4.1 Matriz de riesgo inherente

| IMPACTO ↓ / POSIBILIDAD → | Baja (1) | Media (2) | Alta (3) |
|---|---|---|---|
| **Grave (3)** | 🟨 **Medio (3)**<br>R16 | 🟥 **Alto (6)**<br>R02, R04, R06, R07, R14 | 🟥 **Alto (9)**<br>R01 |
| **Moderada (2)** | 🟩 **Bajo (2)**<br>— | 🟨 **Medio (4)**<br>R03, R05, R08, R09, R10, R15 | 🟥 **Alto (6)**<br>— |
| **Menor (1)** | 🟩 **Bajo (1)**<br>R17 | 🟩 **Bajo (2)**<br>R11, R12 | 🟨 **Medio (3)**<br>R13 |

---

## 5. Plan de mitigación

| ID | Estrategia | Acciones | Etapa |
|---|---|---|---|
| **R01** | **Avoid** | Mantener B1 solo en entorno local con datos sintéticos, sin desplegarlo ni conectarlo a datos reales. Conservar la prohibición de importar `*_unsecure`, `retrieval/unsecure_tool.py` y `db/repository.py` desde S y verificarla con una prueba automática. Archivar B1 tras medir la línea base en la etapa 6 | 1, 6 |
| **R02** | **Mitigate** | Identidad fuera de banda con `SecurityContext`. Tool Gateway con herramientas de esquema cerrado, sin campos de identidad. Guardia de salida con citación obligatoria. Catálogo de 80 a 100 ataques en CI, con 60 % retenido y cero fugas por canarios | 4, 5, 6 |
| **R03** | **Mitigate** | Guardia de salida que bloquee imágenes y enlaces externos de Markdown y exija `chunk_id` válidos. Tratar el contenido recuperado como datos en el prompt. Medir las 8 cargas de `injections.yaml` en cada versión | 5, 6 |
| **R04** | **Mitigate** | Implementar la validación del JWT (RS256 contra JWKS, `iss`, `aud`, `exp`, `nbf`, `azp`, rechazo de `alg: none`). Dejar `ACXES_FRONT_DEMO=0` por defecto y negarse a arrancar con demo fuera de localhost. Excluir `/api/demo/login` de cualquier compilación que no sea de demo. Pruebas de token inválido, expirado y con `aud` incorrecta | 2 |
| **R05** | **Mitigate** | Documentar el procedimiento de alta, baja y cambio de rol. Recertificación trimestral con un script que liste roles sin uso. Habilitar `expires_at` en el PDP para roles temporales. Revisar `claims_drift` persistente. Mantener la separación entre quien administra roles y quien tiene etiquetas (P6) | 3, 5 |
| **R06** | **Mitigate** | S se conecta solo con `acxes_app` y `acxes_pdp` (ya `NOSUPERUSER NOBYPASSRLS`). Prueba automática que falle si la conexión de S es superusuario o tiene `BYPASSRLS`. En entornos no locales, propietario sin superusuario y `sslmode=require`. Mantener los puertos ligados a 127.0.0.1 | 3, 4 |
| **R07** | **Mitigate** | Secretos solo en `.env` ignorado por git. Escaneo de secretos en CI y en pre-commit. Rotar claves de ejemplo y contraseñas de prueba fuera de desarrollo. Sacar `.idea/` del control de versiones. Tope de gasto en Groq y clave con el menor alcance posible | Transversal |
| **R08** | **Mitigate** | TLS en todo entorno no local (Keycloak en modo producción y `sslmode=require`). Patrón BFF con cookie `HttpOnly` y `SameSite`. Cabecera CSP y mantener la inserción de contenido como texto. Access token de 5 a 15 minutos con refresh rotativo | 2 |
| **R09** | **Mitigate** | Completar la revisión manual de la muestra y ampliarla a todos los documentos confidenciales (48) y restringidos (14). Prueba que compare `plan.yaml` con la base. Revisión cruzada de cada cambio a `build_plan.py`. Mantener el `CHECK` de etiquetas (P5) | 3 |
| **R10** | **Mitigate** | Definir la regla de agregación en la guardia de salida e implementar la prueba T06. Límite de tasa por usuario y tope de `k`. Reactivar una alerta mínima por denegaciones repetidas y registrar todo en auditoría | 5, 6 |
| **R11** | **Accept** | Aceptar el residuo. Se reduce por diseño con el mensaje único de denegación (P12 y P17). Revisar al implementar la guardia de salida. No invertir ahora en mitigar diferencias de tiempo | 5 |
| **R12** | **Accept** | Aceptar la indisponibilidad temporal. Documentar el comportamiento fail-closed (P14) con mensaje genérico. La interfaz `LLMClient` ya permite cambiar de proveedor. Reevaluar si el servicio pasa a ser crítico | — |
| **R13** | **Mitigate** | Límite de tasa real (P13, 30 por minuto) en la API de borde. Mantener `AGENT_MAX_ITERATIONS=4` y `llm_max_tokens`. Definir el presupuesto de tokens por turno. Tope de gasto en la consola del proveedor | 4, 5 |
| **R14** | **Transfer** | Trasladar parte del riesgo al proveedor con términos de tratamiento de datos: cero retención y sin uso para entrenamiento, verificados en su documentación. Mantener solo corpus sintético hasta tener ese acuerdo. Evaluar la normativa de habeas data (Ley 1581 de 2012) con asesoría antes de usar datos reales. Alternativa: modelo local. La transferencia no elimina la responsabilidad de la institución como responsable del tratamiento | 4 |
| **R15** | **Mitigate** | Implementar la auditoría con `acxes_app` solo con INSERT (ya definido). Trigger que bloquee UPDATE y DELETE incluso para el propietario. Clasificar el registro como el dato más sensible que contenga. Definir retención y propagar `trace_id` por turno | 5 |
| **R16** | **Mitigate** | Mantener y ampliar la prueba de equivalencia PDP–RLS y el golden set. Aprobar P7 y P8. Sustituir `demo_engine.build_predicate` por el PDP para tener una sola implementación en Python. Revisión cruzada de cada versión de política | 3, 6 |
| **R17** | **Accept** | Aceptar el riesgo (nivel 1). Completar la revisión de la muestra, regenerar los documentos que fallen y no publicar corpus con datos reales | 3 |

Nota: La columna de *Etapa* usa la misma numeración que se encuentra en `documents/FRONTEND.md`, o sea: 2 = API de borde, 3 = PDP y recuperación, 4 = orquestador y Tool Gateway, 5 = guardia de salida, límite de tasa y auditoría, 6 = red team.

---

## 6. Riesgo residual y monitoreo

### 6.1 Valoración residual

| ID | Riesgo residual (lo que permanece) | P | C | Nivel | Clasificación | Indicador de monitoreo y frecuencia |
|---|---|---|---|---|---|---|
| **R01** | Que alguien ejecute B1 fuera del entorno local o con datos reales | 1 | 3 | **3** | 🟨 Medio | Prueba automática de imports de `*_unsecure` desde S en cada commit. Revisión del README y del CI antes de cada entrega |
| **R02** | Ataques nuevos no cubiertos por el catálogo | 1 | 3 | **3** | 🟨 Medio | Fugas por tokens canario en el conjunto retenido (meta: 0). Corrida de red team en CI ante cualquier cambio de prompt o política. Denegaciones por usuario |
| **R03** | Manipulación de la respuesta usando datos autorizados | 1 | 2 | **2** | 🟩 Bajo | Resultado de las 8 cargas por versión. Respuestas marcadas `blocked` o `redacted` por la guardia de salida |
| **R04** | Mala configuración de Keycloak o token robado | 1 | 3 | **3** | 🟨 Medio | Tokens rechazados por motivo. Verificación en el arranque de que `ACXES_FRONT_DEMO` no esté activo fuera de local. Pruebas de token en CI |
| **R05** | Desfase breve entre cambio de rol y su aplicación, o error manual | 1 | 2 | **2** | 🟩 Bajo | `claims_drift` mayor que 0 de forma persistente. Roles sin uso por más de N días. Recertificación trimestral |
| **R06** | Abuso de la credencial del propietario | 1 | 3 | **3** | 🟨 Medio | Verificar `rolsuper=false` y `rolbypassrls=false` para `acxes_app` en cada ejecución. Conexiones por rol en los registros de PostgreSQL. Resultado de `tests/rls` en CI |
| **R07** | Secreto filtrado antes de ser detectado | 1 | 3 | **3** | 🟨 Medio | Hallazgos del escaneo de secretos en CI (meta: 0). Fecha de la última rotación. Consumo anómalo en la consola de Groq |
| **R08** | XSS futuro o token robado con ventana corta | 1 | 2 | **2** | 🟩 Bajo | Tiempo de vida de los tokens. Cabeceras CSP verificadas por versión. Errores 401 por reutilización |
| **R09** | Error puntual de clasificación | 1 | 2 | **2** | 🟩 Bajo | Porcentaje de documentos confidenciales y restringidos revisados (meta: 100 %). Canario presente en todo fragmento confidencial o restringido. Diferencias entre `plan.yaml` y la base (meta: 0) |
| **R10** | Inferencia por agregación que no se elimina del todo | 2 | 2 | **4** | 🟨 Medio | Consultas por usuario por hora. Denegaciones repetidas. Resultado de T06 |
| **R11** | Diferencias residuales de mensaje o de tiempo | 2 | 1 | **2** | 🟩 Bajo | Revisión de los mensajes de error por versión. Diferencia de latencia entre "no existe" y "no autorizado" en las pruebas |
| **R12** | Caídas temporales del proveedor o de un componente | 2 | 1 | **2** | 🟩 Bajo | Porcentaje de solicitudes exitosas. Tasa de error del proveedor. Latencia del PDP frente al límite de 500 ms |
| **R13** | Picos de consumo dentro de los límites definidos | 2 | 1 | **2** | 🟩 Bajo | Tokens por turno y por día. Respuestas 429. Gasto acumulado frente al tope |
| **R14** | Confianza residual en el proveedor | 1 | 3 | **3** | 🟨 Medio | Revisión semestral de los términos del proveedor. Registro de qué niveles de sensibilidad se envían. Incidentes de seguridad que reporte el proveedor |
| **R15** | Fallas de captura o retención del registro | 1 | 2 | **2** | 🟩 Bajo | Intentos de UPDATE o DELETE sobre `audit_log`. Continuidad de `trace_id`. Tamaño y retención del registro. Revisión trimestral |
| **R16** | Error de lógica que las pruebas no cubren | 1 | 3 | **3** | 🟨 Medio | Equivalencia PDP–RLS al 100 % en CI. Denegación falsa de máximo 15 % en el golden set. Eventos de `policy_version` no coincidente |
| **R17** | Dato aislado que parezca real | 1 | 1 | **1** | 🟩 Bajo | Observaciones de `REVISION.md`. Hallazgos de `validate_body` sobre correos y direcciones web |

**Resumen residual:** 🟥 0 altos · 🟨 8 medios (R01, R02, R04, R06, R07, R10, R14, R16) · 🟩 9 bajos.

Los riesgos residuales medios con consecuencia grave (R01, R02, R04, R06, R07, R14, R16) quedan con posibilidad baja. Su consecuencia no baja con los controles, porque de por sí la pérdida de confidencialidad de esos datos sigue siendo grave. Por eso se requiere de aceptación por parte del equipo y monitoreo constante.

### 6.2 Matriz de riesgo residual

| IMPACTO ↓ / POSIBILIDAD → | Baja (1) | Media (2) | Alta (3) |
|---|---|---|---|
| **Grave (3)** | 🟨 **Medio (3)**<br>R01, R02, R04, R06, R07, R14, R16 | 🟥 **Alto (6)**<br>— | 🟥 **Alto (9)**<br>— |
| **Moderada (2)** | 🟩 **Bajo (2)**<br>R03, R05, R08, R09, R15 | 🟨 **Medio (4)**<br>R10 | 🟥 **Alto (6)**<br>— |
| **Menor (1)** | 🟩 **Bajo (1)**<br>R17 | 🟩 **Bajo (2)**<br>R11, R12, R13 | 🟨 **Medio (3)**<br>— |

---

## 7. Seguimiento y revisión

| Momento | Actividad |
|---|---|
| **Cada commit (CI)** | Pruebas de RLS, equivalencia PDP–RLS, golden set, red team (cuando exista), escaneo de secretos y verificación de roles de base de datos |
| **Cada etapa o entrega** | Reevaluar posibilidad y consecuencia de los riesgos cuyo control cambió de estado (por ejemplo, al implementar la API de borde se reevalúan R04 y R08). Actualizar este documento |
| **Cada cambio de `policy_version`** | Revisar R05 y R16 y volver a correr las pruebas de equivalencia |
| **Trimestral** | Recertificación de roles, revisión de términos del proveedor (R14) y de la retención del registro de auditoría (R15) |
| **Tras un incidente o una fuga detectada** | Reevaluar el riesgo afectado, registrar la causa y ajustar el plan de mitigación |

**Criterio de cierre del proyecto:** ninguna secuencia de prompts, incluida la manipulación del historial o de documentos recuperados, debe producir contenido de un fragmento no autorizado para el rol del usuario. Este criterio respalda la reducción de R01, R02 y R03 a su nivel residual.