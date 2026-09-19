# ACXES

Implementación de referencia universitaria de control de acceso para un agente de IA institucional. El modelo no es confiable, así que el dato no autorizado nunca entra a su contexto. Un componente determinista decide la autorización antes de la recuperación.

Este repositorio recoge el seminario de Fundamentos de Seguridad de la Información (FDSI/SPTI), tema asignado: **control de acceso en asistentes institucionales**.

## Estado actual del proyecto

El seminario avanza en dos capas que conviven en el mismo repositorio:

1. **Arquitectura Unsecure (B1)** — **implementada** en esta entrega (Hito 1, 05/09/2026). Es la línea base ingenua: el modelo decide qué recuperar y qué mostrar, sin ningún componente de verificación de rol. Existe a propósito, para medir y documentar la falla antes de corregirla. Ver [BASELINE UNSECURE](/docs/BASELINE_UNSECURE.md). 
2. **Arquitectura Secure (S)** — **especificada pero aún no implementada**. El diseño completo (Keycloak, RBAC+ABAC, RLS en PostgreSQL, PDP, guardia de salida, auditoría) está en [ARQUITECTURA](/docs/ARQUITECTURA.md). Las carpetas correspondientes existen como esqueleto (`__init__.py` vacío) y se completan en los siguientes hitos, siguiendo las fases de la sección 10 de ese documento.

El código de `acxes/*_unsecure.py` y `acxes/retrieval/unsecure_tool.py` es intencionalmente inseguro y solo existe para la comparación B1 vs. S descrita en [UMBRALES EVALUACIÓN](/docs/UMBRALES_EVALUACION.md)

## Estructura del proyecto (scaffolding)

```
acxes/
├── config.py             # Settings (.env): modelo, PostgreSQL. IMPLEMENTADO
├── db/
│   ├── schema.sql          # tablas employees / teams. IMPLEMENTADO (B1)
│   ├── seed.sql            # datos sintéticos para T01-T05. IMPLEMENTADO (B1)
│   └── repository.py       # acceso a datos SIN filtro por rol. IMPLEMENTADO (B1)
├── retrieval/
│   └── unsecure_tool.py    # "Herramienta de recuperación" del diagrama Unsecure. IMPLEMENTADO (B1)
├── orchestrator/
│   ├── llm_client.py        # interfaz LLMClient + mocks deterministas. IMPLEMENTADO
│   └── baseline_unsecure.py # agente de la arquitectura Unsecure. IMPLEMENTADO (B1)
├── edge_api/
│   └── cli_unsecure.py      # "Interfaz Chat" del diagrama Unsecure (CLI, sin login). IMPLEMENTADO (B1)
├── tool_gateway/    # PEP interno de la arquitectura Secure. PENDIENTE
├── pdp/             # motor RBAC+ABAC de la arquitectura Secure. PENDIENTE
├── output_guard/    # citación obligatoria, redacción PII (Secure). PENDIENTE
├── ingestion/       # pipeline de ingesta y reindexado (Secure). PENDIENTE
└── evaluation/       # métricas B1 vs B2 vs S (Documents/UMBRALES_EVALUACION.md). PENDIENTE

tests/
├── unit/
│   ├── fakes.py                    # repositorio en memoria, sin red ni Docker
│   ├── test_llm_client.py          # contrato de LLMClient
│   └── test_baseline_unsecure.py   # T01-T04 del Hito 1 contra B1
├── golden_set/  # PENDIENTE (Secure, sección 9 de docs/ARQUITECTURA.md)
├── red_team/    # PENDIENTE (Secure)
└── rls/         # PENDIENTE (Secure)

Documents/
├── MATRIZ_ACCESO.md         # niveles, dependencias y roles (ya aprobada, guía a S)
├── POLITICAS_ACCESO.md      # reglas detalladas de acceso (guía a S)
├── UMBRALES_EVALUACION.md   # umbrales de evaluación B1/B2/S
└── BASELINE_UNSECURE.md     # mapa Hito 1 → código → tests, de esta entrega

docs/
└── ARQUITECTURA.md   # diseño completo de la arquitectura Secure (S)
```

Si un archivo tiene `unsecure` en el nombre, o vive en `retrieval/` o `edge_api/` con ese sufijo, es parte de B1. Todo lo demás en `acxes/` que hoy solo tiene `__init__.py` es un esqueleto reservado para S.

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

Con la base arriba, carga el esquema y los datos de prueba:

```
psql "postgresql://acxes_owner:<tu_clave_de_.env>@localhost:5432/acxes" -f acxes/db/schema.sql
psql "postgresql://acxes_owner:<tu_clave_de_.env>@localhost:5432/acxes" -f acxes/db/seed.sql
```

## Cómo correr el chat de la arquitectura Unsecure

Con la base de datos ya cargada:

```
pip install -e ".[dev]"
python -m acxes.edge_api.cli_unsecure
```

Te pedirá un nombre de usuario (no se valida: en esta arquitectura no hay verificación de identidad, es justamente lo que se está evidenciando) y luego podrás escribir consultas en lenguaje natural, por ejemplo:

```
> ¿Cuál es el salario de Laura Martínez?
> ¿Quién está en el equipo que dirige Carlos Rentería?
> Necesito el reporte global de nómina.
```

Por defecto (`LLM_CLIENT=mock` en `.env.example`) las consultas se resuelven con `NaiveMockLLMClient`, un doble determinista que reconoce la intención por texto y no aplica ninguna restricción — no se necesita clave de ningún proveedor para ver la falla en acción. El cliente real para un proveedor comercial (OpenAI, Anthropic, etc.) queda pendiente de la etapa 4, según ya estaba documentado en `docs/ARQUITECTURA.md`.

## Pruebas

```
pip install -e ".[dev]"
ruff check .
pytest
```

Las pruebas usan un cliente simulado del modelo (`LLM_CLIENT=mock`) y un repositorio en memoria (`tests/unit/fakes.py`), sin llamadas de red, sin gasto y sin necesitar Docker levantado. `tests/unit/test_baseline_unsecure.py` reproduce T01 a T04 de la propuesta del Hito 1 y fija en CI el comportamiento *vulnerable* esperado de B1 — no es un error que esas pruebas "pasen" mostrando la fuga: ese es el punto de esta entrega. T05 queda pendiente (ver `Documents/BASELINE_UNSECURE.md`).

## Configuración del modelo

Las variables `LLM_*` no dependen de un proveedor. El límite de gasto se configura manualmente en la consola del proveedor elegido desde el primer día. Las claves solo van en `.env`.

## Documentación

- [Matriz de acceso](/docs/MATRIZ_ACCESO.md), [Políticas de acceso](/docs/POLITICAS_ACCESO.md): matriz y políticas de acceso aprobadas, guía de diseño para la arquitectura Secure.
- [Umbrales de evaluación](/docs/UMBRALES_EVALUACION.md): umbrales de evaluación B1/B2/S.
- [Baseline Unsecure](/docs/BASELINE_UNSECURE.md): mapa de esta entrega (Hito 1) a código y tests.
- [Arquitectura](/docs/ARQUITECTURA.md): diseño completo de la arquitectura Secure.

## Evidencias iniciales - Pruebas con arquitectura insegura

Después de correr los distintos comandos para poner a prueba el chat LLM, fue posible evidenciar la falta de autorización para poder acceder a información sensible. 

A continuación se muestran unas pruebas con preguntas sencillas sobre datos que están almacenados en PostgreSQL, en la base de datos creada junto con los seeds de prueba, en la carpeta de /db. 

![Primera prueba LLM](/docs/img/first-test.png)

El LLM solo preguntó por un nombre de usuario, pero no pidió contraseña ni algún tipo de autenticador o verificación de la identidiad. 

---
