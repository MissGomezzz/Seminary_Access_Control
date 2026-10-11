"""Punto de entrada para la evaluación comparativa.

La integración con un entorno concreto se realiza mediante los runners del proyecto; este
comando deja disponible el catálogo y valida el protocolo sin inventar resultados de una base
que no esté levantada.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acxes.evaluation.runner import default_cases


def main() -> int:
    print(json.dumps([case.__dict__ for case in default_cases()], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
