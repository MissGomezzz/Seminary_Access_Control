# Revisión manual de la muestra del corpus

Muestra de 30 documentos de 150 (20 por ciento), con semilla fija. Para cada documento, abra `docs/<slug>.json` y marque:

- **Real**: no contiene datos que parezcan reales (personas, documentos de identidad, cuentas, correos, teléfonos, direcciones).
- **Nivel**: el contenido es coherente con su clasificación. Un documento restringido o confidencial trata algo reservado, y uno público no revela datos individuales.
- **Ficción**: los nombres son ficticios y coinciden con la tabla de usuarios cuando corresponde.

Si un documento falla, anótelo en la columna de observaciones. Se regenera con `python -m acxes.ingestion.generate --only <slug>` tras borrar su archivo.

| Slug | Dependencia | Nivel | Tipo | Real | Nivel | Ficción | Observaciones |
|---|---|---|---|---|---|---|---|
| `reporte-de-estudiantes-en-riesgo-academico` | academica | confidencial | informe | [ ] | [ ] | [ ] | |
| `acta-ordinaria-del-consejo-academico-2026-02` | academica | interno | acta | [ ] | [ ] | [ ] | |
| `acta-ordinaria-del-consejo-academico-2026-04` | academica | interno | acta | [ ] | [ ] | [ ] | |
| `informe-de-matricula-del-periodo-2026-1` | academica | interno | informe | [ ] | [ ] | [ ] | |
| `procedimiento-de-reserva-de-aulas` | academica | interno | procedimiento | [ ] | [ ] | [ ] | |
| `reglamento-interno-de-laboratorios` | academica | interno | politica | [ ] | [ ] | [ ] | |
| `expediente-disciplinario-caso-de-suplantacion-2026` | academica | restringido | expediente | [ ] | [ ] | [ ] | |
| `contrato-con-servicios-tecnologicos-aurora` | financiera | confidencial | contrato | [ ] | [ ] | [ ] | |
| `estados-financieros-detallados-2025` | financiera | confidencial | informe | [ ] | [ ] | [ ] | |
| `evaluacion-de-desempeno-belen-quintero` | financiera | confidencial | evaluacion | [ ] | [ ] | [ ] | |
| `evaluacion-de-desempeno-laura-martinez` | financiera | confidencial | evaluacion | [ ] | [ ] | [ ] | |
| `evaluacion-de-desempeno-sofia-ariza` | financiera | confidencial | evaluacion | [ ] | [ ] | [ ] | |
| `flujo-de-caja-proyectado-2026` | financiera | confidencial | informe | [ ] | [ ] | [ ] | |
| `nomina-individual-carlos-renteria` | financiera | confidencial | nomina | [ ] | [ ] | [ ] | |
| `nomina-individual-laura-martinez` | financiera | confidencial | nomina | [ ] | [ ] | [ ] | |
| `presupuesto-detallado-centro-de-costo-infraestructura` | financiera | confidencial | presupuesto | [ ] | [ ] | [ ] | |
| `instructivo-de-caja-menor` | financiera | interno | procedimiento | [ ] | [ ] | [ ] | |
| `instructivo-de-reembolsos` | financiera | interno | procedimiento | [ ] | [ ] | [ ] | |
| `informe-de-auditoria-de-tesoreria-2026` | financiera | restringido | auditoria | [ ] | [ ] | [ ] | |
| `informe-de-auditoria-interna-2025-q3` | financiera | restringido | auditoria | [ ] | [ ] | [ ] | |
| `informe-de-auditoria-sin-etiquetas-asignadas` | financiera | restringido | auditoria | [ ] | [ ] | [ ] | |
| `investigacion-de-irregularidad-en-pagos-2026` | financiera | restringido | informe | [ ] | [ ] | [ ] | |
| `plan-de-accion-de-auditoria-2026` | financiera | restringido | informe | [ ] | [ ] | [ ] | |
| `procedimiento-de-compras-menores` | institucional | interno | procedimiento | [ ] | [ ] | [ ] | |
| `procedimiento-de-reporte-de-accidentes-de-trabajo` | institucional | interno | procedimiento | [ ] | [ ] | [ ] | |
| `procedimiento-de-solicitud-de-vacaciones` | institucional | interno | procedimiento | [ ] | [ ] | [ ] | |
| `comunicado-sobre-resultados-generales-de-la-evaluacion-docente` | institucional | publico | comunicado (senuelo) | [ ] | [ ] | [ ] | |
| `guia-de-bienvenida-a-la-comunidad-universitaria` | institucional | publico | guia (inyeccion) | [ ] | [ ] | [ ] | |
| `guia-de-transparencia-presupuestal` | institucional | publico | guia (senuelo) | [ ] | [ ] | [ ] | |
| `preguntas-frecuentes-del-portal-de-empleados` | institucional | publico | guia (inyeccion) | [ ] | [ ] | [ ] | |

Revisado por: ____________  Fecha: ____________
