"""Límite de tasa por usuario con ventana deslizante (P13). En memoria y por proceso."""

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int = 30,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Registra una solicitud y devuelve False si `key` ya agotó su cupo en la ventana."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self._window_s:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # no crecer con usuarios que ya no consultan
                cutoff = now - self._window_s
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}
            return True
