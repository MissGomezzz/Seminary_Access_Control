"""Tokens canario para detectar fugas por coincidencia de texto.

Formato `ACXES-CNRY-XXXXXXXX`, con 8 caracteres de un alfabeto sin símbolos ambiguos. Se
derivan del slug con un hash, así que son únicos y reproducibles entre ingestas. Los pone el
código de ingesta y nunca el modelo: un canario en la salida del generador se rechaza.
"""

import hashlib
import re

PREFIX = "ACXES-CNRY-"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 símbolos, sin I, O, 0 ni 1
LENGTH = 8

CANARY_RE = re.compile(r"ACXES-CNRY-[A-Z0-9]{8}")
# Cualquier intento de imitar el formato, aunque sea incompleto
CANARY_PREFIX_RE = re.compile(r"ACXES-CNRY", re.IGNORECASE)


def canary_for(slug: str) -> str:
    digest = hashlib.sha256(f"acxes-canary:{slug}".encode()).digest()
    return PREFIX + "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:LENGTH])


def canary_line(canary: str) -> str:
    return f"Código de control: {canary}"
