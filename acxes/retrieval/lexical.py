"""Búsqueda léxica común a B1, B2 y S.

Las tres arquitecturas recuperan con la misma consulta y el mismo `k`, de modo que la
única diferencia sea la autorización. S añade el predicado del PDP al `WHERE` de esta
misma consulta (`SECURE_SEARCH_CHUNKS_SQL`). B1 la usa tal cual, sin ningún filtro de
autorización.
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
