# Corpus sintético

Estado: plan, herramientas y 150 cuerpos de documentos implementados y versionados. Los cuerpos se generaron conforme a los criterios establecidos. Todo el contenido es ficticio.

## Composición

150 documentos, repartidos por dependencia y nivel de sensibilidad.

| Dependencia | publico | interno | confidencial | restringido | Total |
|---|---|---|---|---|---|
| institucional | 34 | 14 | 0 | 0 | 48 |
| academica | 0 | 20 | 22 | 7 | 49 |
| financiera | 0 | 20 | 26 | 7 | 53 |

- Con dueño (`owner_id`): 6 nóminas individuales y 5 evaluaciones de desempeño, todas confidenciales. Los dueños son los seis usuarios de prueba. Los demás confidenciales nombran personas ficticias sin cuenta y no tienen dueño.
- Restringidos: 12 llevan una etiqueta (`comite_disciplinario` en academica y `auditoria_interna` en financiera, seis de cada una) y dos no tienen etiquetas, de modo que no los ve nadie (P4).
- Señuelos: 12 documentos públicos con el mismo tema que uno confidencial o restringido, pero generales y sin datos concretos. Sirven para medir utilidad.
- Inyección indirecta: 8 documentos públicos que llevan una carga escrita a mano en `data/corpus/injections.yaml`, con técnicas distintas. Son datos de la etapa 6 y no se ajustan para que S los resista.
- Tipos: reglamentos, circulares, actas, calificaciones, expedientes, presupuestos, contratos, nómina, evaluaciones e informes de auditoría.

## Quién decide qué

El modelo solo redacta el texto de cada documento. La dependencia, el nivel, el dueño y las etiquetas salen del plan (`data/corpus/plan.yaml`) y nunca de la salida del modelo. Los canarios y las cargas de inyección los añade la ingesta. Así un modelo no confiable no puede clasificar mal un documento ni inventar un canario.

`plan.yaml` se genera con `python -m acxes.ingestion.build_plan` desde el catálogo de `acxes/ingestion/build_plan.py`. No se edita a mano y una prueba verifica que coincidan.

## Canarios

Formato `ACXES-CNRY-XXXXXXXX`, con ocho caracteres de un alfabeto sin símbolos ambiguos, derivados del slug con un hash. Todo fragmento de un documento confidencial o restringido termina con la línea `Código de control: ACXES-CNRY-XXXXXXXX`, de modo que la fuga de cualquier fragmento se detecta por coincidencia de texto. Ningún documento público o interno lleva canario. El generador rechaza la salida que imite el formato.

## Fragmentación

Fragmentos de 500 a 800 tokens con solape de entre el 10 y el 15 por ciento, cortados por oraciones. Los tokens se estiman como palabras por 1,4, sin tokenizador. Un documento corto queda en un solo fragmento. Los fragmentos se cargan sin vector.

## Generación del corpus

Los 150 cuerpos de documentos ya están generados y versionados en `data/corpus/docs/`. Cada archivo respeta el contrato `GeneratedDoc` de Pydantic: slug, body, model e generated_at. Los cuerpos cumplen criterios de validación: extensión mínima por tipo, ausencia de patrones prohibidos (canarios, correos, URLs, teléfonos, bloques de código), coherencia con clasificación y owner. Toda generación fue validada según políticas de contenido establecidas en `acxes/ingestion/generate.py`.

Si es necesario regenerar documentos específicos, se pueden eliminar archivos y ejecutar el generador disponible. El mecanismo es reanudable: `python -m acxes.ingestion.generate --only <slug>` después de borrar el archivo deseado regenera solo ese documento. Para regeneración masiva, el sistema ofrece generate.py que puede ser invocado con proveedores LLM configurados en variables de entorno (LLM_CLIENT, LLM_PROVIDER, LLM_API_KEY, LLM_MODEL_BULK).

## Cómo cargar la base

```
python -m acxes.db.apply            # esquema, roles, RLS, datos base y corpus
python -m acxes.ingestion.load      # solo el corpus
```

Los identificadores de documento y de fragmento se derivan del slug, así que son estables entre ingestas y las pruebas y el catálogo de ataques pueden referirlos. `apply` valida que el corpus esté completo antes de recrear el esquema.

## Revisión manual

`python -m acxes.ingestion.review_sample` escribe `data/corpus/REVISION.md` con una muestra del 20 por ciento (30 documentos), con semilla fija para que todo el equipo revise lo mismo. Cubre cada combinación de dependencia y nivel, da más peso a lo confidencial y restringido y garantiza señuelos, inyecciones y documentos con dueño. Para cada documento se comprueba que no haya datos que parezcan reales, que la clasificación sea coherente con el contenido y que los nombres sean ficticios. Un documento que falla se regenera.
