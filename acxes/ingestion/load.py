"""Ingesta del corpus sintético a PostgreSQL.

Uso:
    python -m acxes.ingestion.load

Lee `data/corpus/plan.yaml` y los cuerpos de `data/corpus/docs/`, normaliza, añade las cargas
de inyección y los canarios, fragmenta y carga sin vector. Se conecta con el rol propietario,
que es el que migra el esquema. La dependencia, el nivel, el dueño y las etiquetas de cada
fragmento los hereda el trigger del documento (`schema.sql`), nunca se pasan desde aquí.

Es idempotente: reemplaza `documents` y `chunks` en una sola transacción, con identificadores
estables derivados del slug. No importa nada de `acxes.db.repository` ni de los módulos
`unsecure`.
"""

from dataclasses import dataclass
from pathlib import Path

import psycopg

from acxes.config import Settings, get_settings, postgres_dsn
from acxes.ingestion.canary import canary_for, canary_line
from acxes.ingestion.chunking import chunk_text, normalize
from acxes.ingestion.corpus_plan import (
    DOCS_DIR,
    DocSpec,
    Injection,
    chunk_uuid,
    doc_uuid,
    load_generated,
    load_injections,
    load_plan,
)


class CorpusError(Exception):
    """El corpus no está completo o no es coherente con el plan."""


@dataclass(frozen=True)
class LoadSummary:
    documents: int
    chunks: int


def compose_chunks(spec: DocSpec, body: str, injections: dict[str, Injection]) -> list[str]:
    """Textos de los fragmentos de un documento, ya con la carga de inyección y el canario.

    El canario va en cada fragmento y no solo en el documento, de modo que la fuga de cualquier
    fragmento se detecte por coincidencia de texto."""
    paragraphs = normalize(body).split("\n\n")
    if spec.injection:
        payload = injections[spec.injection].text
        position = max(1, len(paragraphs) // 2)
        paragraphs.insert(position, payload)
    chunks = chunk_text("\n\n".join(paragraphs))
    if not spec.carries_canary:
        return [c.text for c in chunks]
    line = canary_line(canary_for(spec.slug))
    return [f"{c.text}\n\n{line}" for c in chunks]


def _check_files(specs: list[DocSpec], docs_dir: Path) -> None:
    expected = {s.slug for s in specs}
    present = {p.stem for p in docs_dir.glob("*.json")} if docs_dir.exists() else set()
    missing = sorted(expected - present)
    orphans = sorted(present - expected)
    if missing:
        raise CorpusError(
            f"Faltan {len(missing)} cuerpos generados (por ejemplo {missing[0]}). Genérelos con: "
            "python -m acxes.ingestion.generate"
        )
    if orphans:
        raise CorpusError(f"Hay archivos sin especificación en el plan: {', '.join(orphans)}")


def verify_corpus(docs_dir: Path = DOCS_DIR) -> None:
    """Falla si el plan y los cuerpos no coinciden o si algún archivo no es válido.
    Se llama antes de tocar la base, para no recrear el esquema y dejarla vacía."""
    specs = load_plan()
    _check_files(specs, docs_dir)
    for spec in specs:
        try:
            generated = load_generated(spec.slug, docs_dir)
        except ValueError as exc:
            raise CorpusError(f"El archivo de {spec.slug} no es un cuerpo válido") from exc
        if generated is None or generated.slug != spec.slug:
            raise CorpusError(f"El cuerpo de {spec.slug} no corresponde al plan")


def load_corpus(
    conn: psycopg.Connection,
    specs: list[DocSpec],
    docs_dir: Path = DOCS_DIR,
    injections: dict[str, Injection] | None = None,
) -> LoadSummary:
    """Reemplaza documentos y fragmentos dentro de la transacción de `conn`."""
    injections = load_injections() if injections is None else injections
    _check_files(specs, docs_dir)

    users = dict(conn.execute("SELECT full_name, id FROM users").fetchall())
    documents: list[tuple] = []
    chunks: list[tuple] = []
    for spec in specs:
        generated = load_generated(spec.slug, docs_dir)
        if generated is None or generated.slug != spec.slug:
            raise CorpusError(f"El cuerpo de {spec.slug} no corresponde al plan")
        if spec.owner is not None and spec.owner not in users:
            raise CorpusError(f"{spec.slug}: el dueño {spec.owner} no existe en users")
        doc_id = doc_uuid(spec.slug)
        documents.append(
            (
                doc_id,
                spec.title,
                spec.dept,
                spec.sensitivity,
                users.get(spec.owner) if spec.owner else None,
                list(spec.acl_tags),
            )
        )
        for index, text in enumerate(compose_chunks(spec, generated.body, injections)):
            chunks.append((chunk_uuid(doc_id, index), doc_id, index, text))

    with conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents")
        cur.executemany(
            "INSERT INTO documents (id, title, dept, sensitivity, owner_id, acl_tags) "
            "VALUES (%s, %s, %s, %s::sensitivity_level, %s, %s)",
            documents,
        )
        # dept, sensitivity, owner_id y acl_tags los completa el trigger desde el documento
        cur.executemany(
            "INSERT INTO chunks (id, doc_id, chunk_index, content) VALUES (%s, %s, %s, %s)",
            chunks,
        )
    return LoadSummary(documents=len(documents), chunks=len(chunks))


def ingest(settings: Settings | None = None, docs_dir: Path = DOCS_DIR) -> LoadSummary:
    settings = settings or get_settings()
    specs = load_plan()
    with psycopg.connect(postgres_dsn(settings)) as conn:
        return load_corpus(conn, specs, docs_dir)


if __name__ == "__main__":
    try:
        summary = ingest()
    except CorpusError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Corpus ingerido: {summary.documents} documentos y {summary.chunks} fragmentos.")
