"""Resultados de la recuperación, comunes a B1 y S.

Viven aquí y no en `acxes/db/repository.py` para que S no tenga que importar el acceso a
datos de B1, que ignora la autorización a propósito.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: str
    doc_id: str
    title: str
    content: str


@dataclass(frozen=True)
class DocumentRecord:
    doc_id: str
    title: str
    chunks: tuple[ChunkHit, ...]


@dataclass(frozen=True)
class ChunkMeta:
    """Metadatos de un fragmento para mostrar sus fuentes al usuario. Sin contenido."""

    chunk_id: str
    doc_id: str
    title: str
    dept: str
    sensitivity: str
    acl_tags: tuple[str, ...]
