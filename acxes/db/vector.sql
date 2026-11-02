-- Etapa opcional de búsqueda vectorial (docs/ARQUITECTURA.md, 6.1 y 6.2).
-- Se aplica justo después de schema.sql. La columna vive en la misma fila del fragmento, así
-- que hereda su clasificación por trigger y la protege la misma política RLS (rls.sql). No
-- cambian los privilegios: GRANT SELECT ON chunks ya la cubre.
-- Sin índice HNSW ni IVFFlat a propósito: la búsqueda es exacta, y un índice aproximado
-- combinado con el filtro del predicado puede devolver menos de k filas.
-- La dimensión la fija EMBEDDING_DIM desde acxes/db/apply.py.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector({dim});
