# ACXES

Implementación de referencia universitaria de control de acceso para un agente de IA institucional. El modelo no es confiable, así que el dato no autorizado nunca entra a su contexto. Un componente determinista decide la autorización antes de la recuperación.

Este repositorio recoge el seminario de Fundamentos de Seguridad de la Información (FDSI/SPTI), tema asignado: **control de acceso en asistentes institucionales**.

## Integrantes

- Sofía Nicolle Ariza Goenaga
- María Belén Quintero Aldana 
- Ángela Gómez Valencia 

## índice 

1. [Estado actual del proyecto](#estado-actual-del-proyecto)
2. [Estructura del proyecto](#estructura-del-proyecto-scaffolding)
3. [Puesta en marcha](#puesta-en-marcha)
4. [Correr chat arquitectura unsecure](#cómo-correr-el-chat-de-la-arquitectura-unsecure)
5. [Pruebas](#pruebas)
6. [Configuración del modelo](#configuración-del-modelo)
7. [Documentación](#documentación)
8. [Uso de IA](#uso-de-ia)
9. [Evidencias iniciales - Unsecure](#evidencias-iniciales---unsecure)

## Estado actual del proyecto

El seminario avanza en dos capas que conviven en el mismo repositorio:

1. **Arquitectura Unsecure (B1)** — **implementada** sobre el esquema compartido de la etapa 1 y con Groq como modelo real. Es la línea base ingenua: el modelo decide qué recuperar y qué mostrar, la única protección son las instrucciones del prompt, la recuperación no filtra y la conexión a la base ignora RLS. Existe a propósito, para medir y documentar la falla antes de corregirla. Ver [BASELINE UNSECURE](/documents/BASELINE_UNSECURE.md).
2. **Arquitectura Secure (S)** — **en construcción**. La etapa 1 (base de datos) ya tiene esquema, roles de base de datos, trigger, RLS con FORCE y un corpus provisional, con sus pruebas. El PDP, el Tool Gateway, la API de borde, la guardia de salida y la auditoría siguen pendientes. El diseño completo está en [ARQUITECTURA](/docs/ARQUITECTURA.md) y el avance por etapa en [PLAN DE IMPLEMENTACIÓN](/docs/PLAN_IMPLEMENTACION.md).

El código de `acxes/*_unsecure.py`, `acxes/retrieval/unsecure_tool.py` y `acxes/db/repository.py` es intencionalmente inseguro y solo existe para la comparación B1 vs. S descrita en [UMBRALES EVALUACIÓN](/docs/UMBRALES_EVALUACION.md). No debe importarse desde S.

## Estructura del proyecto (scaffolding)

```
acxes/
├── config.py               # Settings (.env): modelo, límites, PostgreSQL y sus tres roles. IMPLEMENTADO
├── db/
│   ├── schema.sql            # enum de sensibilidad, users, documents, chunks, audit_log, triggers. IMPLEMENTADO
│   ├── grants.sql            # privilegios de acxes_app y acxes_audit. IMPLEMENTADO
│   ├── rls.sql               # RLS con FORCE y función app_row_visible. IMPLEMENTADO
│   ├── seed.sql              # corpus provisional con canarios. IMPLEMENTADO (lo reemplaza el corpus generado)
│   ├── apply.py              # python -m acxes.db.apply. IMPLEMENTADO
│   └── repository.py         # acceso a datos de B1 SIN filtro, con credencial amplia. IMPLEMENTADO (B1)
├── retrieval/
│   ├── lexical.py            # consulta léxica común a B1, B2 y S. IMPLEMENTADO
│   └── unsecure_tool.py      # herramientas de B1 sin filtro. IMPLEMENTADO (B1)
├── orchestrator/
│   ├── llm_client.py         # interfaz LLMClient, mocks y contrato de herramientas. IMPLEMENTADO
│   ├── groq_client.py        # cliente de Groq con httpx. IMPLEMENTADO
│   ├── tool_catalog.py       # buscar_documentos y leer_documento, esquemas cerrados. IMPLEMENTADO
│   ├── turn.py               # TurnResult común a B1, B2 y S. IMPLEMENTADO
│   └── baseline_unsecure.py  # agente de B1. IMPLEMENTADO (B1)
├── edge_api/
│   └── cli_unsecure.py       # chat de B1 por CLI, sin login. IMPLEMENTADO (B1)
├── tool_gateway/    # PEP interno de la arquitectura Secure. PENDIENTE
├── pdp/             # motor RBAC+ABAC de la arquitectura Secure. PENDIENTE
├── output_guard/    # citación obligatoria, redacción PII (Secure). PENDIENTE
├── ingestion/       # pipeline de ingesta y corpus generado (Secure). PENDIENTE
└── evaluation/      # métricas B1 vs B2 vs S. PENDIENTE

tests/
├── conftest.py                      # omite las pruebas db si no hay PostgreSQL
├── unit/
│   ├── fakes.py                     # repositorio en memoria, sin red ni Docker
│   ├── test_llm_client.py           # contrato de LLMClient y construcción del cliente
│   ├── test_groq_client.py          # cliente de Groq con transporte simulado
│   └── test_baseline_unsecure.py    # T01 a T05 contra B1 y tope de iteraciones
├── rls/                             # pruebas directas contra la base (marcador db)
│   ├── test_rls.py                  # filas exactas por rol, cero filas sin variables, enum, trigger, privilegios
│   └── test_b1_connection.py        # la conexión de B1 ignora RLS
├── golden_set/  # PENDIENTE
└── red_team/    # PENDIENTE

docs/                        # para Claude y el equipo, casi todo ignorado por git
├── ARQUITECTURA.md          # diseño completo de la arquitectura Secure (S)
├── PLAN_IMPLEMENTACION.md   # plan, etapas y estado de avance
├── DESVIACIONES.md          # registro de desviaciones
├── VARIABLES_SESION.md      # variables de sesión para RLS
├── UMBRALES_EVALUACION.md   # umbrales de evaluación B1/B2/S
└── SETUP_WINDOWS.md         # guía de instalación en Windows

documents/                   # documentación pública del equipo
├── MATRIZ_ACCESO.md         # niveles, dependencias y roles (aprobada)
├── POLITICAS_ACCESO.md      # políticas P1 a P17 (aprobadas)
├── BASELINE_UNSECURE.md     # mapa de B1 a código y tests
└── img/                     # imágenes de pruebas realizadas
```

Si un archivo tiene `unsecure` en el nombre, o es `db/repository.py`, es parte de B1. Las carpetas de `acxes/` que solo tienen `__init__.py` son un esqueleto reservado para S.

## Puesta en marcha

Requisitos: Docker con Compose y Python 3.12 o superior.

Entorno completo con un solo comando (levanta PostgreSQL **y** Keycloak, aunque esta entrega solo usa PostgreSQL — Keycloak es para cuando se implemente la arquitectura Secure, no hace daño dejarlo corriendo):

```
# Windows
powershell -File scripts/up.ps1

# Linux o macOS
bash scripts/up.sh
```

El script crea `.env` desde `.env.example` si no existe, levanta los servicios y espera a que estén sanos. Las claves de `.env.example` son de ejemplo y deben cambiarse.

Si solo quieres la base de datos para probar la arquitectura Unsecure:

```
docker compose up -d --wait postgres
```

Con la base arriba, define en `.env` las tres claves de PostgreSQL (`POSTGRES_PASSWORD`, `POSTGRES_APP_PASSWORD` y `POSTGRES_AUDIT_PASSWORD`) y carga el esquema, los roles, RLS y los datos provisionales:

```
pip install -e ".[dev]"
python -m acxes.db.apply
```

Es idempotente: recrea las tablas y los datos cada vez. No necesita `psql`.

## Cómo correr el chat de la arquitectura Unsecure

Con la base cargada:

```
python -m acxes.edge_api.cli_unsecure
```

Te muestra los seis usuarios de prueba y te deja elegir uno, sin contraseña, porque en esta arquitectura no hay verificación de identidad y eso es justamente lo que se está evidenciando. Luego puedes escribir consultas en lenguaje natural, por ejemplo:

```
> ¿Cuál es el salario de Laura Martínez?
> Necesito el presupuesto detallado por centro de costo.
> Necesito el acta del comité disciplinario.
```

Con `LLM_CLIENT=mock` (valor por defecto) las consultas las resuelve `NaiveMockLLMClient`, un doble determinista que no necesita clave. Con `LLM_CLIENT=real` usa Groq. Cada respuesta imprime cuántos fragmentos recibió el modelo, los tokens y la latencia.

## Pruebas

```
ruff check .
pytest
```

Las pruebas unitarias usan un cliente simulado del modelo y un repositorio en memoria, sin red, sin gasto y sin Docker. `tests/unit/test_baseline_unsecure.py` reproduce T01 a T05 y fija en CI el comportamiento *vulnerable* esperado de B1: no es un error que esas pruebas "pasen" mostrando la fuga, ese es el punto de esta entrega. La prueba de agregación del Hito 1 queda pendiente (ver [BASELINE UNSECURE](/documents/BASELINE_UNSECURE.md)).

Las pruebas de `tests/rls/` llevan el marcador `db`, se conectan directo a PostgreSQL con los roles `acxes_app` y `acxes_owner`, y se omiten si la base no está disponible o no tiene datos. Para correrlas: levantar la base y ejecutar `python -m acxes.db.apply`. El CI levanta un servicio de PostgreSQL y las corre siempre.

## Configuración del modelo

El modelo se accede por la interfaz `LLMClient`. El proveedor elegido es **Groq** (API compatible con OpenAI) y el cliente usa `httpx`. Para usarlo, en `.env`:

```
LLM_CLIENT=real
LLM_API_KEY=<tu clave de Groq>
```

`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL_AGENT` y `LLM_MODEL_BULK` ya tienen valores en `.env.example`. Los identificadores de modelo se verificaron en la documentación de Groq el 2026-09-21 y deben revisarse antes de cambiarlos. El modelo del agente, `openai/gpt-oss-120b`, pasó la prueba de aceptación de B1. `LLM_BASE_URL` debe ser `https://api.groq.com/openai/v1`. Los límites comunes a B1 y S son `AGENT_MAX_ITERATIONS=4` y `RETRIEVAL_K=5`.

El límite de gasto se configura manualmente en la consola del proveedor desde el primer día. La clave solo va en `.env`, que está ignorado por git. El CI usa siempre el cliente simulado.

## Documentación

- [Matriz de acceso](/documents/MATRIZ_ACCESO.md), [Políticas de acceso](/documents/POLITICAS_ACCESO.md): matriz y políticas de acceso aprobadas, guía de diseño para la arquitectura Secure.
- [Umbrales de evaluación](/docs/UMBRALES_EVALUACION.md): umbrales de evaluación B1/B2/S.
- [Baseline Unsecure](/documents/BASELINE_UNSECURE.md): mapa de B1 a código y tests.
- [Arquitectura](/docs/ARQUITECTURA.md): diseño completo de la arquitectura Secure.
- [Plan de implementación](/docs/PLAN_IMPLEMENTACION.md): etapas, estado de avance y concreción de B1 y Groq.
- [Variables de sesión](/docs/VARIABLES_SESION.md): variables que fija el servicio de recuperación para RLS.
- [Guía de instalación en Windows](/docs/SETUP_WINDOWS.md).

## Uso de IA

Para poder realizar la codificación del proyecto con todos sus componentes y llamados al agente LLM tanto en la arquitectura inicial como en la arquitecutra final segura, se apoyó del uso de Claude. 

## Evidencias iniciales - Unsecure

Después de correr los distintos comandos para poner a prueba el chat LLM, fue posible evidenciar la falta de autorización para poder acceder a información sensible. 

A continuación se muestran unas pruebas con preguntas sencillas sobre datos que están almacenados en PostgreSQL. La captura es de la primera versión de B1 (Hito 1, con las tablas `employees` y `teams` y un modelo simulado). Desde entonces B1 usa el esquema compartido y Groq, y la evidencia se repetirá con esa versión. 

![Primera prueba LLM](/documents/img/first-test.png)

El LLM solo preguntó por un nombre de usuario, pero no pidió contraseña ni algún tipo de autenticador o verificación de la identidiad. 

---
