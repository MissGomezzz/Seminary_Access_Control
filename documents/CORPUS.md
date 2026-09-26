# Corpus sintético

Estado: plan, herramientas y 150 cuerpos de documentos implementados, versionados e ingeridos (150 documentos y 174 fragmentos). Pendiente la revisión manual de la muestra. Todo el contenido es ficticio.

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

Los 150 cuerpos de documentos están redactados y versionados en `data/corpus/docs/`. Cada archivo respeta el contrato `GeneratedDoc` de Pydantic: slug, body, model e generated_at, y el campo `model` indica quién lo redactó. Las reglas de contenido de `acxes/ingestion/generate.py` (`validate_body`) son extensión mínima por tipo, ausencia de patrones prohibidos (canarios, correos, URLs, teléfonos, bloques de código) y coherencia con el dueño. No todos los cuerpos las cumplen:

- Los 20 documentos de `academica/interno` se redactaron el 2026-09-21 y cumplen todas las reglas. Sustituyeron archivos vacíos.
- De los otros 130, 116 no alcanzan el 85 por ciento de la extensión pedida. La mediana es el 25 por ciento y el mínimo es un informe de auditoría de 38 palabras pedido a 700. Once contienen un correo electrónico y tres una dirección web. Son una excepción aceptada por el equipo y está registrada en `docs/DESVIACIONES.md`.
- Consecuencia: 174 fragmentos para 150 documentos, casi todos en un solo fragmento. Limita la utilidad del golden set de la etapa 3.

Para listar los que no cumplen, valide cada cuerpo con `validate_body`. Un documento que se regenere sí queda sujeto a esas reglas.

Antes de recrear el esquema, `apply` verifica que cada archivo sea un `GeneratedDoc` válido y que corresponda al plan (`verify_corpus`), de modo que un archivo vacío o dañado detiene la carga sin tocar la base.

Si es necesario regenerar documentos específicos, se pueden eliminar archivos y ejecutar el generador disponible. El mecanismo es reanudable: `python -m acxes.ingestion.generate --only <slug>` después de borrar el archivo deseado regenera solo ese documento. Para regeneración masiva, el sistema ofrece generate.py que puede ser invocado con proveedores LLM configurados en variables de entorno (LLM_CLIENT, LLM_PROVIDER, LLM_API_KEY, LLM_MODEL_BULK).

## Cómo cargar la base

```
python -m acxes.db.apply            # esquema, roles, RLS, datos base y corpus
python -m acxes.ingestion.load      # solo el corpus
```

Los identificadores de documento y de fragmento se derivan del slug, así que son estables entre ingestas y las pruebas y el catálogo de ataques pueden referirlos. `apply` valida que el corpus esté completo antes de recrear el esquema.

## Revisión manual

`python -m acxes.ingestion.review_sample` escribe `data/corpus/REVISION.md` con una muestra del 20 por ciento (30 documentos), con semilla fija para que todo el equipo revise lo mismo. Cubre cada combinación de dependencia y nivel, da más peso a lo confidencial y restringido y garantiza señuelos, inyecciones y documentos con dueño. Para cada documento se comprueba que no haya datos que parezcan reales, que la clasificación sea coherente con el contenido y que los nombres sean ficticios. Un documento que falla se regenera.
