"""S no importa código de las líneas base, que es inseguro a propósito (CLAUDE.md)."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "acxes"
SECURE_MODULES = [
    ROOT / "security_context.py",
    *sorted((ROOT / "pdp").glob("*.py")),
    ROOT / "retrieval" / "secure.py",
    ROOT / "retrieval" / "types.py",
    ROOT / "retrieval" / "lexical.py",
]
FORBIDDEN = ("acxes.db.repository", "unsecure")


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("path", SECURE_MODULES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_s_no_importa_modulos_inseguros(path):
    prohibidos = {n for n in _imports(path) if any(f in n for f in FORBIDDEN)}
    assert prohibidos == set()
