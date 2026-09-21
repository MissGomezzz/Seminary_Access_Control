"""Búsqueda léxica común a B1, B2 y S.

Las tres arquitecturas recuperan con la misma consulta y el mismo `k`, de modo que la
única diferencia sea la autorización. S añadirá el predicado del PDP al `WHERE` de esta
misma consulta. B1 la usa tal cual, sin ningún filtro de autorización.
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


def keywords_to_or_query(keywords: list[str]) -> str:
    """Combina las palabras clave con OR para `websearch_to_tsquery`."""
    return " OR ".join(k.strip() for k in keywords if k.strip())
