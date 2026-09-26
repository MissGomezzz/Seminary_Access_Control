"""Muestra estratificada del 20 por ciento del corpus para la revisión manual.

Uso:
    python -m acxes.ingestion.review_sample

Escribe `data/corpus/REVISION.md` con una lista de control por documento. La semilla es fija,
de modo que todo el equipo revisa la misma muestra. Cubre cada combinación de dependencia y
nivel y da más peso a lo confidencial y restringido, que es donde un dato que parezca real o
una clasificación incoherente cuesta más. Además garantiza señuelos, inyecciones y documentos
con dueño. La revisión busca datos que parezcan reales, clasificaciones incoherentes con el
contenido y nombres que no sean ficticios.
"""

import math
import random
from collections import defaultdict

from acxes.ingestion.corpus_plan import CORPUS_DIR, DocSpec, load_plan

SEED = 20260921
FRACTION = 0.20
REVIEW_PATH = CORPUS_DIR / "REVISION.md"
_WEIGHT = {"publico": 1, "interno": 1, "confidencial": 2, "restringido": 2}
# Mínimos por tipo especial dentro de la muestra
_MIN_KIND = {"senuelo": 2, "inyeccion": 2}
_MIN_OWNED = 3


def sample_size(total: int) -> int:
    return math.ceil(total * FRACTION)


def pick_sample(specs: list[DocSpec], seed: int = SEED) -> list[DocSpec]:
    rng = random.Random(seed)
    size = sample_size(len(specs))
    ordered = sorted(specs, key=lambda s: s.slug)
    chosen: dict[str, DocSpec] = {}

    def take(candidates: list[DocSpec], count: int) -> None:
        pool = [c for c in candidates if c.slug not in chosen]
        rng.shuffle(pool)
        for spec in pool[:count]:
            chosen[spec.slug] = spec

    cells: dict[tuple[str, str], list[DocSpec]] = defaultdict(list)
    for spec in ordered:
        cells[(spec.dept, spec.sensitivity)].append(spec)
    for key in sorted(cells):
        take(cells[key], 1)
    for kind, minimum in _MIN_KIND.items():
        have = sum(1 for s in chosen.values() if s.kind == kind)
        take([s for s in ordered if s.kind == kind], max(0, minimum - have))
    have_owned = sum(1 for s in chosen.values() if s.owner)
    take([s for s in ordered if s.owner], max(0, _MIN_OWNED - have_owned))

    # El resto, al azar y con más peso para lo reservado
    remaining = [s for s in ordered if s.slug not in chosen]
    weights = [_WEIGHT[s.sensitivity] for s in remaining]
    while len(chosen) < size and remaining:
        pick = rng.choices(range(len(remaining)), weights=weights, k=1)[0]
        chosen[remaining[pick].slug] = remaining.pop(pick)
        weights.pop(pick)
    return sorted(chosen.values(), key=lambda s: (s.dept, s.sensitivity, s.slug))


_INTRO = """# Revisión manual de la muestra del corpus

Muestra de {n} documentos de {total} (20 por ciento), con semilla fija. Para cada documento, abra `docs/<slug>.json` y marque:

- **Real**: no contiene datos que parezcan reales (personas, documentos de identidad, cuentas, correos, teléfonos, direcciones).
- **Nivel**: el contenido es coherente con su clasificación. Un documento restringido o confidencial trata algo reservado, y uno público no revela datos individuales.
- **Ficción**: los nombres son ficticios y coinciden con la tabla de usuarios cuando corresponde.

Si un documento falla, anótelo en la columna de observaciones. Se regenera con `python -m acxes.ingestion.generate --only <slug>` tras borrar su archivo.

| Slug | Dependencia | Nivel | Tipo | Real | Nivel | Ficción | Observaciones |
|---|---|---|---|---|---|---|---|"""


def render(sample: list[DocSpec], total: int) -> str:
    lines = _INTRO.format(n=len(sample), total=total).splitlines()
    for spec in sample:
        tag = "" if spec.kind == "normal" else f" ({spec.kind})"
        lines.append(
            f"| `{spec.slug}` | {spec.dept} | {spec.sensitivity} | {spec.doc_type}{tag} "
            "| [ ] | [ ] | [ ] | |"
        )
    lines += ["", "Revisado por: ____________  Fecha: ____________", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    specs = load_plan()
    picked = pick_sample(specs)
    REVIEW_PATH.write_text(render(picked, len(specs)), encoding="utf-8", newline="\n")
    print(f"{len(picked)} documentos de la muestra escritos en {REVIEW_PATH}")
