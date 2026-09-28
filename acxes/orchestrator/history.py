"""Historial de conversación de S, guardado en el servidor (P15).

El cliente solo envía el mensaje nuevo, así que no puede falsificar turnos previos. La clave
es `(user_id, session_id)` y cada entrada recuerda la versión de política y la huella de
autorización con que se creó. Si cualquiera de las dos cambia, el historial anterior se
descarta: un cambio de rol, dependencia o etiquetas en la base no arrastra contexto obtenido
con los permisos anteriores.

Entre turnos solo se guardan el mensaje del usuario y la respuesta final. Los resultados de
herramientas viven solo dentro del turno en que se recuperaron.
"""

import threading
from dataclasses import dataclass, field
from uuid import UUID

from acxes.orchestrator.llm_client import LLMMessage


@dataclass(frozen=True)
class HistoryKey:
    user_id: UUID
    session_id: str
    policy_version: str
    authz_fingerprint: str


@dataclass
class _Entry:
    policy_version: str
    authz_fingerprint: str
    messages: list[LLMMessage] = field(default_factory=list)


class InMemoryHistoryStore:
    def __init__(self, max_turns: int = 10) -> None:
        self._max_messages = 2 * max_turns
        self._entries: dict[tuple[UUID, str], _Entry] = {}
        self._lock = threading.Lock()

    def load(self, key: HistoryKey) -> list[LLMMessage]:
        with self._lock:
            entry = self._entries.get((key.user_id, key.session_id))
            if entry is None or not _matches(entry, key):
                return []
            return list(entry.messages)

    def append_turn(self, key: HistoryKey, user_message: str, assistant_text: str) -> None:
        with self._lock:
            slot = (key.user_id, key.session_id)
            entry = self._entries.get(slot)
            if entry is None or not _matches(entry, key):
                entry = _Entry(key.policy_version, key.authz_fingerprint)
                self._entries[slot] = entry
            entry.messages.append(LLMMessage(role="user", content=user_message))
            entry.messages.append(LLMMessage(role="assistant", content=assistant_text))
            del entry.messages[: -self._max_messages]


def _matches(entry: _Entry, key: HistoryKey) -> bool:
    return (
        entry.policy_version == key.policy_version
        and entry.authz_fingerprint == key.authz_fingerprint
    )
