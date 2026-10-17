"""TEMPORAL, solo para desarrollo: trazas para diagnosticar denegaciones en S.

Todas las llamadas usan `dev_audit(...)` y llevan el prefijo [DEV-AUDIT], así que se
retiran borrando este módulo y buscando `dev_audit` en el código. No registra contenido de
documentos, salarios, JWT ni claves.
"""

import logging
import sys

_log = logging.getLogger("acxes.devaudit")
if not _log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s [DEV-AUDIT]"
                                            " %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.DEBUG)
    _log.propagate = False


def dev_audit(message: str, *args) -> None:
    _log.debug(message, *args)


def preview(text: str | None, limit: int = 160) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"
