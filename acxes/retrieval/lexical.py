"""Búsqueda léxica, e híbrida opcional, común a B1, B2 y S.

Las tres arquitecturas recuperan con la misma consulta y el mismo `k`, de modo que la
única diferencia sea la autorización. S añade el predicado del PDP al `WHERE` de esta
misma consulta (`SECURE_SEARCH_CHUNKS_SQL`). B1 la usa tal cual, sin ningún filtro de
autorización. Con `RETRIEVAL_MODE=hybrid` ambas usan la variante híbrida
(`HYBRID_SEARCH_CHUNKS_SQL` y `SECURE_HYBRID_SEARCH_CHUNKS_SQL`) con la misma regla.
"""

# Con parámetros ligados. `%(q)s` es la consulta OR y `%(k)s` el límite fijado por configuración
SEARCH_CHUNKS_SQL = """
SELECT c.id, c.doc_id, d.title, c.content
FROM chunks c
JOIN documents d ON d.id = c.doc_id
WHERE c.content_tsv @@ websearch_to_tsquery('spanish', %(q)s)
ORDER BY ts_rank_cd(c.content_tsv, websearch_to_tsquery('spanish', %(q)s)) DESC, c.id
LIMIT %(k)s
"""


def predicate_clause(alias: str) -> str:
    """Regla de visibilidad de documents/POLITICAS_ACCESO.md sobre la tabla `alias`, con los
    campos del predicado del PDP como parámetros ligados: `%(depts)s`, `%(max_sensitivity)s`,
    `%(owner_id)s` y `%(acl_tags)s`. Es la misma regla que aplica RLS en `app_row_visible`."""
    return f"""(
    ({alias}.dept = ANY(%(depts)s)
     AND {alias}.sensitivity < 'restringido'
     AND {alias}.sensitivity <= %(max_sensitivity)s::sensitivity_level)
    OR ({alias}.owner_id = %(owner_id)s AND {alias}.sensitivity <= 'confidencial')
    OR ({alias}.sensitivity = 'restringido' AND {alias}.acl_tags && %(acl_tags)s::text[])
)"""


# Misma consulta, orden y límite que SEARCH_CHUNKS_SQL, con el predicado en el WHERE
SECURE_SEARCH_CHUNKS_SQL = f"""
SELECT c.id, c.doc_id, d.title, c.content
FROM chunks c
JOIN documents d ON d.id = c.doc_id
WHERE c.content_tsv @@ websearch_to_tsquery('spanish', %(q)s)
  AND {predicate_clause("c")}
ORDER BY ts_rank_cd(c.content_tsv, websearch_to_tsquery('spanish', %(q)s)) DESC, c.id
LIMIT %(k)s
"""


def keywords_to_or_query(keywords: list[str]) -> str:
    """Combina las palabras clave con OR para `websearch_to_tsquery`."""
    return " OR ".join(k.strip() for k in keywords if k.strip())


def keywords_to_text(keywords: list[str]) -> str:
    """Texto que se convierte en el vector de la consulta en modo híbrido."""
    return " ".join(k.strip() for k in keywords if k.strip())


def _hybrid_sql(pred: str) -> str:
    """Búsqueda híbrida: rama léxica y rama vectorial exacta, fusionadas con Reciprocal Rank
    Fusion. Sin reranking. Parámetros además de los léxicos: `%(qv)s` (vector de la consulta
    como texto), `%(n)s` (candidatos por rama), `%(rrf_k)s` y `%(min_sim)s` (similitud coseno
    mínima o NULL).

    `pred` va en el WHERE de cada rama, antes de su ORDER BY ... LIMIT, de modo que el filtro
    se aplica antes de recuperar y una rama nunca gasta candidatos en filas no autorizadas. Se
    repite al elegir el mejor fragmento como red adicional. Nunca se devuelve la columna
    embedding.

    Devuelve a lo sumo un fragmento por documento, el de mayor puntaje, para que un documento
    largo no ocupe varios de los `k` lugares. `leer_documento` sigue dando el documento entero."""
    return f"""
WITH lex AS (
    SELECT c.id,
           row_number() OVER (ORDER BY ts_rank_cd(c.content_tsv, q.query) DESC, c.id) AS r
    FROM chunks c
    CROSS JOIN websearch_to_tsquery('spanish', %(q)s) AS q(query)
    WHERE c.content_tsv @@ q.query
      AND {pred}
    ORDER BY r
    LIMIT %(n)s
),
vec AS (
    SELECT c.id,
           row_number() OVER (ORDER BY c.embedding <=> %(qv)s::vector, c.id) AS r
    FROM chunks c
    WHERE c.embedding IS NOT NULL
      AND (%(min_sim)s::float8 IS NULL OR 1 - (c.embedding <=> %(qv)s::vector) >= %(min_sim)s)
      AND {pred}
    ORDER BY r
    LIMIT %(n)s
),
fused AS (
    SELECT u.id, SUM(1.0 / (%(rrf_k)s + u.r)) AS score
    FROM (SELECT id, r FROM lex UNION ALL SELECT id, r FROM vec) u
    GROUP BY u.id
),
best AS (
    SELECT DISTINCT ON (c.doc_id) c.id, f.score
    FROM fused f
    JOIN chunks c ON c.id = f.id
    WHERE {pred}
    ORDER BY c.doc_id, f.score DESC, c.id
)
SELECT c.id, c.doc_id, d.title, c.content
FROM best b
JOIN chunks c ON c.id = b.id
JOIN documents d ON d.id = c.doc_id
ORDER BY b.score DESC, c.id
LIMIT %(k)s
"""


# B1: misma consulta híbrida, sin ningún filtro de autorización
HYBRID_SEARCH_CHUNKS_SQL = _hybrid_sql("TRUE")
# S: el predicado del PDP en cada rama y en la consulta final
SECURE_HYBRID_SEARCH_CHUNKS_SQL = _hybrid_sql(predicate_clause("c"))
