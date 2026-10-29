"""Búsqueda híbrida sin base: embedder de prueba, configuración, ingesta y servicio de S."""

import math
from datetime import UTC, datetime

import pytest

from acxes.config import Settings
from acxes.ingestion.corpus_plan import load_plan
from acxes.ingestion.load import CorpusError, _embed_chunks, embedding_text, load_corpus
from acxes.pdp.model import Decision, Predicate, Sensitivity
from acxes.retrieval.embedding import HashEmbedder, build_embedder, to_pgvector
from acxes.retrieval.lexical import (
    HYBRID_SEARCH_CHUNKS_SQL,
    SECURE_HYBRID_SEARCH_CHUNKS_SQL,
    predicate_clause,
)
from acxes.retrieval.secure import RetrievalDenied, RetrievalError, SecureRetrievalService
from tests.unit.test_pdp import SOFIA

KEYWORDS = ["vacaciones", "permiso", "licencia"]


def _settings(**over) -> Settings:
    return Settings(_env_file=None, **over)


def _hybrid(**over) -> Settings:
    return _settings(retrieval_mode="hybrid", embedding_backend="hash", **over)


def _cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


# --- Embedder de prueba ---------------------------------------------------------------


def test_hash_embedder_es_determinista_normalizado_y_de_la_dimension_pedida():
    e = HashEmbedder(64)
    a, b = e.embed_query("Política de vacaciones"), e.embed_query("Política de vacaciones")
    assert a == b and len(a) == 64
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0)


def test_hash_embedder_ignora_tildes_y_mayusculas_y_acerca_textos_parecidos():
    e = HashEmbedder(256)
    assert e.embed_query("Nómina") == e.embed_query("nomina")
    base = e.embed_query("política de vacaciones del personal")
    cerca = e.embed_query("vacaciones del personal")
    lejos = e.embed_query("presupuesto de tesorería")
    assert _cos(base, cerca) > _cos(base, lejos)


def test_texto_vacio_da_vector_nulo_sin_dividir_por_cero():
    assert HashEmbedder(8).embed_query("") == [0.0] * 8


def test_literal_pgvector():
    assert to_pgvector([1.0, -0.5, 0.25]) == "[1,-0.5,0.25]"


# --- Configuración --------------------------------------------------------------------


def test_en_modo_lexico_no_hay_embedder():
    assert build_embedder(_settings()) is None


def test_en_modo_hibrido_el_embedder_se_crea_una_vez_por_proceso():
    a, b = build_embedder(_hybrid()), build_embedder(_hybrid())
    assert isinstance(a, HashEmbedder) and a is b and a.dim == 1024


def test_los_candidatos_no_pueden_ser_menos_que_k():
    with pytest.raises(ValueError):
        _settings(retrieval_k=10, retrieval_candidates=5)


# --- SQL ------------------------------------------------------------------------------


def test_la_consulta_segura_filtra_en_cada_rama_y_en_la_final():
    pred = predicate_clause("c")
    assert SECURE_HYBRID_SEARCH_CHUNKS_SQL.count(pred) == 3
    assert pred not in HYBRID_SEARCH_CHUNKS_SQL
    # A lo sumo un fragmento por documento
    assert "DISTINCT ON (c.doc_id)" in SECURE_HYBRID_SEARCH_CHUNKS_SQL
    # Nunca se devuelve el vector
    final = SECURE_HYBRID_SEARCH_CHUNKS_SQL.rsplit("SELECT c.id, c.doc_id", 1)[1]
    assert "embedding" not in final.split("FROM")[0]


# --- Ingesta --------------------------------------------------------------------------


def test_los_vectores_con_otra_dimension_se_rechazan():
    class Corto(HashEmbedder):
        def embed_documents(self, texts):
            return [[0.0] * (self.dim - 1) for _ in texts]

    with pytest.raises(CorpusError):
        _embed_chunks(Corto(8), ["texto"])
    assert _embed_chunks(None, ["texto"]) is None


class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def executemany(self, sql, rows):
        self.log.append((sql, list(rows)))


class _FakeConn:
    """Devuelve los usuarios del seed y registra las escrituras."""

    def __init__(self, specs):
        owners = {s.owner for s in specs if s.owner}
        self.users = [(name, f"id-{i}", "financiera") for i, name in enumerate(sorted(owners))]
        self.log: list = []

    def execute(self, sql, params=None):
        return iter(self.users)

    def cursor(self):
        return _FakeCursor(self.log)


def test_la_ingesta_guarda_un_vector_por_fragmento_sobre_titulo_y_texto_final():
    specs = load_plan()
    conn = _FakeConn(specs)
    summary = load_corpus(conn, specs, embedder=HashEmbedder(16))

    sql, rows = next(e for e in conn.log if "INSERT INTO chunks" in e[0])
    assert "embedding" in sql and "::vector" in sql
    assert summary.embedded == summary.chunks == len(rows)
    _, _, _, text, vector = rows[0]
    # El título entra al vector, no al contenido guardado
    esperado = HashEmbedder(16).embed_query(embedding_text(specs[0].title, text))
    assert vector == to_pgvector(esperado)


def test_la_ingesta_sin_embedder_no_toca_la_columna():
    specs = load_plan()
    conn = _FakeConn(specs)
    summary = load_corpus(conn, specs)

    sql, _ = next(e for e in conn.log if "INSERT INTO chunks" in e[0])
    assert "embedding" not in sql and summary.embedded == 0


# --- Servicio de recuperación de S ----------------------------------------------------


def _decision(allowed=True) -> Decision:
    if not allowed:
        return Decision("deny", SOFIA.policy_version, datetime.now(UTC), reason="test")
    predicate = Predicate(("institucional", "financiera"), Sensitivity.interno, SOFIA.user_id, ())
    return Decision("allow", SOFIA.policy_version, datetime.now(UTC), predicate)


class _SpyEmbedder(HashEmbedder):
    def __init__(self, error=None):
        super().__init__(1024)
        self.calls = 0
        self.error = error

    def embed_query(self, text):
        self.calls += 1
        if self.error:
            raise self.error
        return super().embed_query(text)


class _RecordingConnect:
    """Conexión falsa: registra la consulta y no devuelve filas."""

    def __init__(self):
        self.queries: list[tuple] = []

    def __call__(self, _dsn):
        outer = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql, params=None):
                outer.queries.append((sql, params))

            def fetchall(self):
                return []

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def transaction(self):
                return self

            def cursor(self):
                return Cur()

        return Conn()


def test_con_denegacion_no_se_calcula_el_vector_ni_se_abre_conexion():
    embedder, connect = _SpyEmbedder(), _RecordingConnect()
    service = SecureRetrievalService(_hybrid(), connect=connect, embedder=embedder)

    with pytest.raises(RetrievalDenied):
        service.search(SOFIA, _decision(allowed=False), KEYWORDS)
    assert embedder.calls == 0 and connect.queries == []


def test_en_modo_hibrido_usa_la_consulta_segura_hibrida():
    embedder, connect = _SpyEmbedder(), _RecordingConnect()
    service = SecureRetrievalService(_hybrid(), connect=connect, embedder=embedder)

    assert service.search(SOFIA, _decision(), KEYWORDS) == []
    sql, params = connect.queries[-1]
    assert sql == SECURE_HYBRID_SEARCH_CHUNKS_SQL
    assert params["qv"].startswith("[") and params["n"] == 20 and params["rrf_k"] == 60
    assert params["depts"] == ["institucional", "financiera"]
    assert embedder.calls == 1


def test_un_fallo_del_modelo_es_un_error_generico_sin_volver_a_lo_lexico():
    embedder = _SpyEmbedder(error=RuntimeError("detalle interno"))
    connect = _RecordingConnect()
    service = SecureRetrievalService(_hybrid(), connect=connect, embedder=embedder)

    with pytest.raises(RetrievalError, match="^error de recuperación$"):
        service.search(SOFIA, _decision(), KEYWORDS)
    assert connect.queries == []


def test_en_modo_lexico_no_se_usa_el_embedder():
    embedder, connect = _SpyEmbedder(), _RecordingConnect()
    service = SecureRetrievalService(_settings(), connect=connect, embedder=embedder)

    service.search(SOFIA, _decision(), KEYWORDS)
    assert embedder.calls == 0
    assert "qv" not in connect.queries[-1][1]
