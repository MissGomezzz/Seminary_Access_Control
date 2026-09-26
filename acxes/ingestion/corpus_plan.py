"""Modelos del corpus sintético y su carga desde `data/corpus/`.

El plan (`plan.yaml`) es la única fuente de la clasificación de cada documento. El modelo de
lenguaje solo redacta el texto: dependencia, nivel, dueño y etiquetas nunca salen de su
salida. Las restricciones repiten las del esquema (`acxes/db/schema.sql`) para fallar antes
de tocar la base.
"""

import re
import unicodedata
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

CORPUS_DIR = Path(__file__).resolve().parents[2] / "data" / "corpus"
PLAN_PATH = CORPUS_DIR / "plan.yaml"
DOCS_DIR = CORPUS_DIR / "docs"
INJECTIONS_PATH = CORPUS_DIR / "injections.yaml"

Dept = Literal["institucional", "academica", "financiera"]
Sensitivity = Literal["publico", "interno", "confidencial", "restringido"]
Kind = Literal["normal", "senuelo", "inyeccion"]

# P6: etiqueta y dependencia a la que pertenece
ACL_TAG_DEPT: dict[str, str] = {
    "comite_disciplinario": "academica",
    "auditoria_interna": "financiera",
}

# Nombres de los usuarios de prueba, tal como están en `seed.sql`
USER_NAMES = (
    "Sofía Ariza",
    "Belén Quintero",
    "Ángela Gómez",
    "Laura Martínez",
    "Carlos Rentería",
    "Diego Fajardo",
)

INSTITUTION = "Instituto Universitario Meridiano"

_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def slugify(text: str) -> str:
    plain = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def doc_uuid(slug: str) -> UUID:
    """Identificador estable del documento a partir de su slug, para que las pruebas y el
    catálogo de ataques puedan referirlo entre ingestas."""
    return uuid5(NAMESPACE_URL, f"acxes:doc:{slug}")


def chunk_uuid(doc_id: UUID, index: int) -> UUID:
    return uuid5(doc_id, f"chunk:{index}")


class DocSpec(BaseModel):
    """Especificación de un documento del corpus. Todo lo que decide el acceso vive aquí."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    title: str
    dept: Dept
    sensitivity: Sensitivity
    owner: str | None = None
    acl_tags: tuple[str, ...] = ()
    doc_type: str
    hint: str = Field(description="Indicación de contenido para el prompt de generación")
    min_words: int = Field(ge=100)
    kind: Kind = "normal"
    decoy_of: str | None = None
    injection: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "DocSpec":
        if not _SLUG.match(self.slug):
            raise ValueError(f"slug inválido: {self.slug}")
        # P5: las etiquetas solo existen en el nivel restringido
        if self.acl_tags and self.sensitivity != "restringido":
            raise ValueError(f"{self.slug}: las etiquetas solo se permiten en restringido")
        for tag in self.acl_tags:
            if tag not in ACL_TAG_DEPT:
                raise ValueError(f"{self.slug}: etiqueta desconocida {tag}")
            if ACL_TAG_DEPT[tag] != self.dept:
                raise ValueError(f"{self.slug}: la etiqueta {tag} no corresponde a {self.dept}")
        # P3: el dueño solo cuenta hasta confidencial
        if self.owner is not None:
            if self.owner not in USER_NAMES:
                raise ValueError(f"{self.slug}: el dueño {self.owner} no es un usuario de prueba")
            if self.sensitivity not in ("interno", "confidencial"):
                raise ValueError(f"{self.slug}: un dueño solo aplica a interno o confidencial")
        if self.kind == "senuelo":
            if not (self.decoy_of and self.sensitivity == "publico"):
                raise ValueError(f"{self.slug}: un señuelo es público y referencia a su tema")
        elif self.decoy_of:
            raise ValueError(f"{self.slug}: solo un señuelo lleva decoy_of")
        if self.kind == "inyeccion":
            if not (self.injection and self.sensitivity == "publico"):
                raise ValueError(f"{self.slug}: una inyección es pública y lleva su carga")
        elif self.injection:
            raise ValueError(f"{self.slug}: solo una inyección lleva carga")
        return self

    @property
    def carries_canary(self) -> bool:
        """Todo documento confidencial o restringido lleva token canario."""
        return self.sensitivity in ("confidencial", "restringido")


class GeneratedDoc(BaseModel):
    """Archivo `docs/<slug>.json`: el texto generado y cómo se generó."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    body: str
    model: str
    generated_at: str


class Injection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    technique: str
    text: str


def load_plan(path: Path = PLAN_PATH) -> list[DocSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs = [DocSpec.model_validate(item) for item in raw["documents"]]
    check_plan(specs)
    return specs


def check_plan(specs: list[DocSpec]) -> None:
    by_slug = {s.slug: s for s in specs}
    if len(by_slug) != len(specs):
        raise ValueError("Hay slugs repetidos en el plan del corpus")
    if len({s.title for s in specs}) != len(specs):
        raise ValueError("Hay títulos repetidos en el plan del corpus")
    for s in specs:
        if s.decoy_of:
            target = by_slug.get(s.decoy_of)
            if target is None or not target.carries_canary:
                raise ValueError(f"{s.slug}: decoy_of debe apuntar a un confidencial o restringido")


def load_injections(path: Path = INJECTIONS_PATH) -> dict[str, Injection]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    injections = [Injection.model_validate(item) for item in raw["injections"]]
    by_id = {i.id: i for i in injections}
    if len(by_id) != len(injections):
        raise ValueError("Hay identificadores de inyección repetidos")
    return by_id


def load_generated(slug: str, docs_dir: Path = DOCS_DIR) -> GeneratedDoc | None:
    path = docs_dir / f"{slug}.json"
    if not path.exists():
        return None
    return GeneratedDoc.model_validate_json(path.read_text(encoding="utf-8"))
