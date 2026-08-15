"""Core-owned opaque selection lifecycle for any release provider."""

from __future__ import annotations

import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from media_finder_sdk import (
    DownloadArtifact,
    ReleaseCandidate,
    ReleaseProvider,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
)


class ReleaseSelectionExpired(ValueError):
    def __init__(self) -> None:
        super().__init__("release_search_token_expired")


@dataclass(frozen=True, slots=True)
class SelectedRelease:
    token: str
    snapshot: SafeReleaseSnapshot

    @property
    def title(self) -> str:
        return self.snapshot.title

    @property
    def indexer(self) -> str:
        return self.snapshot.indexer


@dataclass(frozen=True, slots=True)
class ResolvedRelease:
    snapshot: SafeReleaseSnapshot
    artifact: DownloadArtifact


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    candidate: ReleaseCandidate
    expires_at: datetime


class ReleaseSelectionCache:
    """Bounded process-local cache; private module selections never reach browsers."""

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=10),
        max_entries: int = 512,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0) or max_entries < 1:
            raise ValueError("release_selection_cache_bounds_invalid")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = RLock()

    def put(self, candidate: ReleaseCandidate) -> str:
        with self._lock:
            self._purge_expired()
            token = secrets.token_urlsafe(32)
            while token in self._entries:
                token = secrets.token_urlsafe(32)
            self._entries[token] = _CacheEntry(
                candidate=candidate,
                expires_at=self._clock() + self._ttl,
            )
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return token

    def get(self, token: str) -> ReleaseCandidate:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or entry.expires_at <= self._clock():
                self._entries.pop(token, None)
                raise ReleaseSelectionExpired
            self._entries.move_to_end(token)
            return entry.candidate

    def take(self, token: str) -> ReleaseCandidate:
        with self._lock:
            candidate = self.get(token)
            del self._entries[token]
            return candidate

    def _purge_expired(self) -> None:
        now = self._clock()
        expired = [token for token, entry in self._entries.items() if entry.expires_at <= now]
        for token in expired:
            del self._entries[token]


class ReleaseSelectionService:
    """Join a specialized provider to core-owned opaque token semantics."""

    def __init__(self, provider: ReleaseProvider, cache: ReleaseSelectionCache) -> None:
        self._provider = provider
        self._cache = cache

    def search(self, query: ReleaseSearchQuery) -> tuple[SelectedRelease, ...]:
        return tuple(
            SelectedRelease(token=self._cache.put(candidate), snapshot=candidate.snapshot)
            for candidate in self._provider.search(query)
        )

    def inspect(self, token: str) -> SafeReleaseSnapshot:
        return self._cache.get(token).snapshot

    def resolve(self, token: str) -> ResolvedRelease:
        candidate = self._cache.take(token)
        return ResolvedRelease(
            snapshot=candidate.snapshot,
            artifact=self._provider.resolve(candidate.selection),
        )

    def close(self) -> None:
        self._provider.close()


__all__ = [
    "ReleaseSelectionCache",
    "ReleaseSelectionExpired",
    "ReleaseSelectionService",
    "ResolvedRelease",
    "SelectedRelease",
]
