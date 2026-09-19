# Línea base Unsecure (B1) — Hito 1

Estado: implementación inicial entregada el 05/09/2026. Corresponde a la
sección 4 de `FDSI-GP-01_05-09-2026.pdf` (arquitectura Unsecure) y a la
línea base "B1 (línea base ingenua)" mencionada en `UMBRALES_EVALUACION.md`.

## De la propuesta al código

| Elemento del diagrama (Hito 1) | Módulo |
|---|---|
| Usuario | argumento `usuario` en `UnsecureAgent.responder` (sin validar, solo etiqueta) |
| Interfaz Chat | `acxes/edge_api/cli_unsecure.py` |
| Modelo (decide qué recuperar y qué mostrar) | `acxes/orchestrator/baseline_unsecure.py` + `NaiveMockLLMClient` en modo `mock` |
| Herramienta de recuperación (sin filtro por rol) | `acxes/retrieval/unsecure_tool.py` |
| Base de datos institucional | `acxes/db/schema.sql`, `acxes/db/seed.sql`, `acxes/db/repository.py` |

## Pruebas propuestas → tests automatizados

| Prueba (Hito 1) | Test | Resultado que fija en CI |
|---|---|---|
| T01 | `test_t01_consulta_directa_fuera_de_rol_expone_el_salario` | Un empleado obtiene el salario de otra persona |
| T02 | `test_t02_manipulacion_del_mensaje_no_cambia_nada_porque_no_hay_restriccion` | El "intento de manipulación" no cambia nada porque no hay restricción que evadir: el sistema ya es permisivo por defecto |
| T03 | `test_t03_supervisor_ve_datos_de_un_equipo_que_no_dirige` | Un supervisor ve la nómina de un equipo que no dirige |
| T04 | `test_t04_administrador_recibe_el_reporte_global_de_nomina` | Control positivo: la arquitectura, aunque insegura, es funcionalmente útil |
| T05 | *Pendiente* | Requiere lógica de agregación mínima que esta línea base no implementa a propósito; se deja como caso a resolver en la arquitectura Secure |

## Qué NO incluye esta entrega, a propósito

Todo lo que ya está especificado en `docs/ARQUITECTURA.md` para la
arquitectura **Secure** (Keycloak, `SecurityContext`, PDP con reglas
RBAC+ABAC, RLS en PostgreSQL, guardia de salida, auditoría) sigue sin
implementarse. Las carpetas `acxes/pdp/`, `acxes/tool_gateway/`,
`acxes/output_guard/`, `acxes/ingestion/` y `acxes/evaluation/` siguen
vacías (`__init__.py` únicamente) y se completan en los siguientes hitos,
según las fases descritas en la sección 10 de `docs/ARQUITECTURA.md`.
