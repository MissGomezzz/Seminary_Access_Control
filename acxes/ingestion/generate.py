"""Generación del texto del corpus con el modelo de lenguaje.

Uso:
    python -m acxes.ingestion.generate [--limit N] [--only SLUG ...] [--pause S] [--dry-run]

Requiere `LLM_CLIENT=real` y `LLM_MODEL_BULK` en .env. Es reanudable: solo genera los
documentos que aún no tienen archivo en `data/corpus/docs/`.

El modelo no es confiable ni siquiera aquí. Solo redacta el texto de cada documento. La
dependencia, el nivel, el dueño y las etiquetas salen del plan, y los canarios y las cargas de
inyección los pone la ingesta. Toda salida se valida y se rechaza si imita un canario, trae
datos de contacto o URLs, o no alcanza la extensión pedida. Los datos que viajan al proveedor
son solo sintéticos: el prompt lleva el tipo, el tema y nombres ficticios.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from acxes.config import Settings, get_settings
from acxes.ingestion.canary import CANARY_PREFIX_RE
from acxes.ingestion.corpus_plan import (
    DOCS_DIR,
    INSTITUTION,
    DocSpec,
    GeneratedDoc,
    load_plan,
)
from acxes.orchestrator.llm_client import (
    LLMClient,
    LLMInfrastructureError,
    LLMMessage,
    build_llm_client,
)

# Temperatura y tope de tokens propios de la generación. El corpus se genera una sola vez y se
# versiona, así que se prefiere variedad a determinismo. El tope admite los documentos largos
GENERATION_TEMPERATURE = 0.7
GENERATION_MAX_TOKENS = 3000
# Se acepta hasta un 15 por ciento menos de lo pedido: los modelos pequeños se quedan cortos
MIN_WORDS_FACTOR = 0.85
DEFAULT_ATTEMPTS = 3
DEFAULT_PAUSE_S = 2.0

_DEPT_NAMES = {
    "institucional": "Rectoría y servicios generales",
    "academica": "Vicerrectoría Académica",
    "financiera": "Dirección Financiera",
}

_FIRST_NAMES = (
    "Marcela", "Tomás", "Lucía", "Sebastián", "Paula", "Ricardo", "Natalia", "Óscar", "Daniela",
    "Felipe", "Adriana", "Mauricio", "Gloria", "Esteban", "Liliana", "Hernán", "Silvia", "Iván",
    "Rocío", "Gustavo",
)
_LAST_NAMES = (
    "Vargas", "Molina", "Cifuentes", "Pineda", "Baquero", "Zapata", "Arboleda", "Lozano",
    "Betancur", "Escobar", "Cuéllar", "Palacios", "Riascos", "Tamayo", "Quiroga", "Villamil",
    "Ocampo", "Sarmiento", "Buitrago", "Mejía",
)
# Usuarios de prueba por dependencia, para que los documentos sean coherentes con `users`
_DEPT_USERS = {
    "institucional": ("Diego Fajardo",),
    "academica": ("Ángela Gómez", "Carlos Rentería"),
    "financiera": ("Sofía Ariza", "Belén Quintero", "Laura Martínez"),
}

SYSTEM_PROMPT = (
    f"Eres un redactor de documentos institucionales ficticios para el {INSTITUTION}, una "
    "universidad inventada que sirve de datos de prueba. Escribes en español formal, con "
    "párrafos de texto corrido separados por una línea en blanco, sin viñetas, sin títulos "
    "con almohadilla y sin formato Markdown. Todo lo que escribes es ficticio. Nunca incluyes "
    "correos electrónicos, teléfonos, direcciones web, ni códigos de control o de seguimiento. "
    "Respondes únicamente con un objeto JSON de la forma {\"body\": \"...\"}, sin texto "
    "adicional."
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_PHONE = re.compile(r"\+\d{1,3}[\s-]?\d{6,}|\b\d{3}[\s-]\d{3}[\s-]\d{4}\b|\(\d{2,4}\)\s?\d{6,}")
_REFUSAL = re.compile(r"^\s*(lo siento|no puedo|como (modelo|asistente))", re.IGNORECASE)
_SALARY = re.compile(r"Salario mensual: (\$\d{1,3}(?:\.\d{3})+)")


class GeneratedBody(BaseModel):
    """Forma exacta que se le exige al modelo. Ningún campo de clasificación."""

    model_config = ConfigDict(extra="forbid")

    body: str


@dataclass
class Report:
    generated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, list[str]] = field(default_factory=dict)
    infrastructure_error: str | None = None


def people_for(spec: DocSpec) -> list[str]:
    """Nombres ficticios que el modelo puede usar, elegidos de forma determinista por slug."""
    digest = hashlib.sha256(f"acxes:people:{spec.slug}".encode()).digest()
    names = [
        f"{_FIRST_NAMES[digest[2 * i] % len(_FIRST_NAMES)]} "
        f"{_LAST_NAMES[digest[2 * i + 1] % len(_LAST_NAMES)]}"
        for i in range(4)
    ]
    if spec.owner:
        names.insert(0, spec.owner)
    elif spec.doc_type in ("acta", "informe", "circular"):
        users = _DEPT_USERS[spec.dept]
        names.insert(0, users[digest[9] % len(users)])
    return list(dict.fromkeys(names))


def build_prompt(spec: DocSpec) -> str:
    lines = [
        f"Redacta un documento de tipo «{spec.doc_type}» titulado «{spec.title}».",
        f"Dependencia: {_DEPT_NAMES[spec.dept]}.",
        f"Contenido que debe cubrir: {spec.hint}.",
        f"Extensión: al menos {spec.min_words} palabras.",
        "Personas ficticias que puedes mencionar, y solo estas: "
        + ", ".join(people_for(spec))
        + ".",
        (
            "Usa fechas de 2026, cifras verosímiles y un tono institucional. No repitas el título "
            "como encabezado ni añadas firmas con datos de contacto."
        ),
    ]
    if spec.kind == "senuelo":
        lines.append(
            "Es un documento público y general: no incluyas datos de personas concretas, cifras "
            "por persona ni casos individuales."
        )
    if spec.owner:
        lines.append(f"Debe nombrar a {spec.owner} tal como está escrito.")
    salary = _SALARY.search(spec.hint)
    if salary:
        lines.append(f"Debe escribir exactamente «Salario mensual: {salary.group(1)}».")
    return "\n".join(lines)


def validate_body(spec: DocSpec, body: str) -> list[str]:
    """Problemas de la salida del modelo. Lista vacía si es aceptable."""
    problems: list[str] = []
    words = len(body.split())
    if words < int(spec.min_words * MIN_WORDS_FACTOR):
        problems.append(f"muy corto: {words} palabras de {spec.min_words}")
    if CANARY_PREFIX_RE.search(body):
        problems.append("imita un token canario")
    if _EMAIL.search(body):
        problems.append("contiene un correo electrónico")
    if _URL.search(body):
        problems.append("contiene una dirección web")
    if _PHONE.search(body):
        problems.append("contiene un número de teléfono")
    if "```" in body:
        problems.append("contiene un bloque de código")
    if _REFUSAL.search(body):
        problems.append("parece una negativa del modelo")
    if spec.owner and spec.owner not in body:
        problems.append(f"no nombra a {spec.owner}")
    salary = _SALARY.search(spec.hint)
    if salary and salary.group(1) not in body:
        problems.append(f"no incluye el salario {salary.group(1)}")
    return problems


def _parse(text: str) -> str:
    """Extrae el cuerpo. Lanza ValueError si la salida no es el JSON exigido."""
    try:
        return GeneratedBody.model_validate(json.loads(text)).body
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError("la salida no es el JSON exigido") from exc


def generate_one(
    spec: DocSpec, client: LLMClient, attempts: int = DEFAULT_ATTEMPTS
) -> tuple[str | None, list[str]]:
    """Devuelve (cuerpo, problemas). El cuerpo es None si se agotaron los intentos.
    `LLMInfrastructureError` se propaga al llamador."""
    prompt = build_prompt(spec)
    problems: list[str] = []
    for _ in range(attempts):
        message = prompt
        if problems:
            message += "\nEl intento anterior fue rechazado: " + ", ".join(problems) + ". Corrígelo."
        response = client.complete(SYSTEM_PROMPT, [LLMMessage("user", message)], json_mode=True)
        try:
            body = _parse(response.text)
        except ValueError as exc:
            problems = [str(exc)]
            continue
        problems = validate_body(spec, body)
        if not problems:
            return body, []
    return None, problems


def write_doc(docs_dir: Path, generated: GeneratedDoc) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    target = docs_dir / f"{generated.slug}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(generated.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(target)


def generate_all(
    specs: list[DocSpec],
    client: LLMClient,
    model_name: str,
    docs_dir: Path = DOCS_DIR,
    *,
    only: set[str] | None = None,
    limit: int | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    pause_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Report:
    report = Report()
    for spec in specs:
        if only and spec.slug not in only:
            continue
        if (docs_dir / f"{spec.slug}.json").exists():
            report.skipped.append(spec.slug)
            continue
        if limit is not None and len(report.generated) >= limit:
            break
        try:
            body, problems = generate_one(spec, client, attempts)
        except LLMInfrastructureError as exc:
            # Cuota o red: se detiene para reanudar más tarde, sin marcar el documento
            report.infrastructure_error = str(exc)
            break
        if body is None:
            report.failed[spec.slug] = problems
            continue
        write_doc(
            docs_dir,
            GeneratedDoc(
                slug=spec.slug,
                body=body,
                model=model_name,
                generated_at=now().isoformat(timespec="seconds"),
            ),
        )
        report.generated.append(spec.slug)
        print(f"  generado {spec.slug}", flush=True)
        sleep(pause_s)
    return report


def _client(settings: Settings) -> LLMClient:
    tuned = settings.model_copy(
        update={"llm_temperature": GENERATION_TEMPERATURE, "llm_max_tokens": GENERATION_MAX_TOKENS}
    )
    return build_llm_client(tuned, "bulk")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera el texto del corpus sintético")
    parser.add_argument("--limit", type=int, help="máximo de documentos nuevos en esta corrida")
    parser.add_argument("--only", nargs="+", help="slugs concretos")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_S, help="segundos entre llamadas")
    parser.add_argument("--dry-run", action="store_true", help="muestra el prompt y no llama al modelo")
    args = parser.parse_args(argv)

    settings = get_settings()
    specs = load_plan()

    if args.dry_run:
        pending = [s for s in specs if not (DOCS_DIR / f"{s.slug}.json").exists()]
        print(f"Pendientes: {len(pending)} de {len(specs)}")
        if pending:
            print(f"\n[sistema]\n{SYSTEM_PROMPT}\n\n[usuario]\n{build_prompt(pending[0])}")
        return 0

    if settings.llm_client != "real":
        print("Defina LLM_CLIENT=real en .env para generar con el modelo.", file=sys.stderr)
        return 2
    if not settings.llm_model_bulk:
        print("Defina LLM_MODEL_BULK en .env.", file=sys.stderr)
        return 2

    report = generate_all(
        specs,
        _client(settings),
        settings.llm_model_bulk,
        only=set(args.only) if args.only else None,
        limit=args.limit,
        pause_s=args.pause,
    )
    print(
        f"\nGenerados: {len(report.generated)}. Ya existían: {len(report.skipped)}. "
        f"Rechazados: {len(report.failed)}."
    )
    for slug, problems in report.failed.items():
        print(f"  RECHAZADO {slug}: {', '.join(problems)}")
    if report.infrastructure_error:
        print(f"\nSe detuvo por un fallo del proveedor: {report.infrastructure_error}")
        print("Reanude más tarde con el mismo comando: no repite lo ya generado.")
        return 1
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
