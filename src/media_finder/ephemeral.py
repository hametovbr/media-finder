"""Bounded process-memory storage for opaque, short-lived UI selections."""

from __future__ import annotations

import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class EphemeralTokenExpired(LookupError):
    """A token is missing, expired, evicted, consumed, or from another process."""


@dataclass(frozen=True, slots=True)
class _Entry[T]:
    value: T
    expires_at: datetime


class EphemeralCache[T]:
    """Capacity- and TTL-bounded cache using cryptographically opaque tokens."""

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=15),
        max_entries: int = 512,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0) or max_entries < 1:
            raise ValueError("ephemeral cache bounds must be positive")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self._entries: OrderedDict[str, _Entry[T]] = OrderedDict()

    def put(self, value: T) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        while token in self._entries:
            token = secrets.token_urlsafe(32)
        self._entries[token] = _Entry(value, self._clock() + self._ttl)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return token

    def get(self, token: str) -> T:
        entry = self._entries.get(token)
        if entry is None or entry.expires_at <= self._clock():
            self._entries.pop(token, None)
            raise EphemeralTokenExpired
        self._entries.move_to_end(token)
        return entry.value

    def pop(self, token: str) -> T:
        value = self.get(token)
        del self._entries[token]
        return value

    def _purge(self) -> None:
        now = self._clock()
        expired = [token for token, entry in self._entries.items() if entry.expires_at <= now]
        for token in expired:
            del self._entries[token]
