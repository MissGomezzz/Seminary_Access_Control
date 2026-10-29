"""Modelos de embeddings para la búsqueda híbrida (etapa opcional de docs/ARQUITECTURA.md).

El modelo corre en el mismo proceso que la ingesta y el servicio de recuperación. Ningún
fragmento ni consulta sale del sistema para calcular su vector, porque el contenido
confidencial y restringido no puede cruzar esa frontera.

- `local`: `sentence-transformers` con el modelo de `EMBEDDING_MODEL` (por defecto
  `BAAI/bge-m3`, multilingüe, 1024 dimensiones y contexto de 8192 tokens, de modo que los
  fragmentos de 500 a 800 tokens no se truncan). Requiere el extra `embeddings`.
- `hash`: vectores deterministas por hashing de palabras. Solo para pruebas y CI, sin descargar
  ningún modelo. Su calidad semántica es la de una bolsa de palabras.
"""

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from acxes.config import Settings


class EmbeddingError(Exception):
    """El modelo no está disponible o devolvió un vector inesperado."""


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Modelo local de `sentence-transformers`. Se carga en el primer uso."""

    def __init__(self, model_name: str, dim: int, batch_size: int = 16) -> None:
        self.model_name = model_name
        self.dim = dim
        self._batch_size = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    'Falta sentence-transformers. Instale el extra: pip install -e ".[embeddings]"'
                ) from exc
            model = SentenceTransformer(self.model_name)
            # Renombrado en versiones recientes de sentence-transformers
            get_dim = getattr(model, "get_embedding_dimension", None) or getattr(
                model, "get_sentence_embedding_dimension"
            )
            actual = get_dim()
            if actual != self.dim:
                raise EmbeddingError(
                    f"{self.model_name} produce {actual} dimensiones y EMBEDDING_DIM es {self.dim}"
                )
            self._model = model
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            list(texts), batch_size=self._batch_size, normalize_embeddings=True
        )
        return [_checked(v.tolist(), self.dim) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_WORD = re.compile(r"\w+")


class HashEmbedder:
    """Bolsa de palabras con hashing estable y normalización L2. Solo para pruebas."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        folded = unicodedata.normalize("NFKD", text.lower())
        folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
        for word in _WORD.findall(folded):
            digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            vector[value % self.dim] += 1.0 if (value >> 63) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector] if norm else vector


def _checked(vector: list[float], dim: int) -> list[float]:
    if len(vector) != dim:
        raise EmbeddingError(f"vector de {len(vector)} dimensiones, se esperaban {dim}")
    return vector


def to_pgvector(vector: Sequence[float]) -> str:
    """Literal de texto que acepta el cast `::vector` de pgvector."""
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def build_embedder(settings: Settings) -> Embedder | None:
    """None en modo léxico. Una sola instancia por configuración y proceso, para no cargar el
    modelo dos veces cuando B1 y S conviven (por ejemplo en scripts/evaluate.py)."""
    if settings.retrieval_mode != "hybrid":
        return None
    return _cached_embedder(
        settings.embedding_backend, settings.embedding_model, settings.embedding_dim
    )


@lru_cache(maxsize=4)
def _cached_embedder(backend: str, model_name: str, dim: int) -> Embedder:
    if backend == "hash":
        return HashEmbedder(dim)
    return SentenceTransformerEmbedder(model_name, dim)
