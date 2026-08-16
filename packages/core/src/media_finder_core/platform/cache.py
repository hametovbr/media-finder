"""Bounded process-memory storage for opaque application selections."""

from __future__ import annotations

import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock

from .clock import Clock, SystemClock


class EphemeralTokenExpired(LookupError):
    """The token is missing, expired, evicted, consumed, or process-local."""


@dataclass(frozen=True, slots=True)
class _Entry[T]:
    value: T
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _CallableClock:
    operation: Callable[[], datetime]

    def now(self) -> datetime:
        return self.operation()


class EphemeralCache[T]:
    """Capacity- and TTL-bounded cache using cryptographically opaque tokens."""

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=15),
        max_entries: int = 512,
        clock: Clock | Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0) or max_entries < 1:
            raise ValueError("cache_bounds_invalid")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = (
            SystemClock()
            if clock is None
            else _CallableClock(clock)
            if callable(clock) and not hasattr(clock, "now")
            else clock
        )
        self._entries: OrderedDict[str, _Entry[T]] = OrderedDict()
        self._lock = RLock()

    def put(self, value: T) -> str:
        with self._lock:
            self._purge()
            token = secrets.token_urlsafe(32)
            while token in self._entries:
                token = secrets.token_urlsafe(32)
            self._entries[token] = _Entry(value, self._clock.now() + self._ttl)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return token

    def get(self, token: str) -> T:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or entry.expires_at <= self._clock.now():
                self._entries.pop(token, None)
                raise EphemeralTokenExpired
            self._entries.move_to_end(token)
            return entry.value

    def pop(self, token: str) -> T:
        with self._lock:
            value = self.get(token)
            del self._entries[token]
            return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _purge(self) -> None:
        with self._lock:
            now = self._clock.now()
            expired = [token for token, entry in self._entries.items() if entry.expires_at <= now]
            for token in expired:
                del self._entries[token]


__all__ = ["EphemeralCache", "EphemeralTokenExpired"]
