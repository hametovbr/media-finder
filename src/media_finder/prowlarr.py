"""Internal, process-local Prowlarr search adapter.

Sensitive artifact resolution data lives only in ``SearchResultCache``. Public search
results intentionally contain an opaque selection token and a sanitized snapshot.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from .sdk.types import DownloadArtifact, MagnetArtifact, TorrentArtifact

SAFE_GUID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
INFOHASH = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})$")
SUSPECT_SECRET_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{24,}$")
SECRET_MARKERS = ("passkey", "token", "session", "credential", "secret")
DOWNLOAD_ROUTE_SEGMENTS = {"announce", "download", "downloadfile", "torrent"}


class ExpiredSearchToken(ValueError):
    """Raised without reflecting the rejected opaque token."""

    def __init__(self) -> None:
        super().__init__("release_search_token_expired")


class ProwlarrTransport(Protocol):
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]: ...
    def fetch_torrent(self, url: str) -> bytes: ...


class ProwlarrError(RuntimeError):
    """A safe internal integration error without upstream response content."""


class HttpxProwlarrTransport:
    """Synchronous Prowlarr API transport resolving its API key per request."""

    def __init__(
        self,
        base_url: str,
        api_key_ref: str,
        secret_resolver: Callable[[str], str],
        client: httpx.Client,
    ) -> None:
        if not api_key_ref.startswith("env:"):
            raise ValueError("prowlarr_api_key_reference_required")
        self._base_url = base_url.rstrip("/")
        self._api_key_ref = api_key_ref
        self._secret_resolver = secret_resolver
        self._client = client

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        params = {"query": query, "type": "search", **filters}
        try:
            response = self._client.get(
                f"{self._base_url}/api/v1/search",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            raise ProwlarrError("prowlarr_search_failed") from None
        if not isinstance(payload, list):
            raise ProwlarrError("prowlarr_search_failed")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def fetch_torrent(self, url: str) -> bytes:
        try:
            response = self._client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.content
        except Exception:
            raise ProwlarrError("prowlarr_download_failed") from None

    def _headers(self) -> dict[str, str]:
        try:
            api_key = self._secret_resolver(self._api_key_ref)
        except Exception:
            raise ProwlarrError("prowlarr_configuration_invalid") from None
        return {"X-Api-Key": api_key}


@dataclass(frozen=True, slots=True)
class ReleaseSnapshot:
    title: str
    indexer: str
    guid: str | None = None
    infohash: str | None = None
    source_page_url: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseSearchResult:
    token: str
    title: str
    indexer: str
    snapshot: ReleaseSnapshot


@dataclass(frozen=True, slots=True)
class ResolvedRelease:
    snapshot: ReleaseSnapshot
    artifact: DownloadArtifact


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    snapshot: ReleaseSnapshot
    magnet_uri: str | None
    download_url: str | None
    expires_at: datetime


class SearchResultCache:
    """A bounded, intentionally non-durable cache for selected release artifacts."""

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=10),
        max_entries: int = 512,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0) or max_entries < 1:
            raise ValueError("search cache bounds must be positive")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()

    def put(
        self,
        snapshot: ReleaseSnapshot,
        *,
        magnet_uri: str | None,
        download_url: str | None,
    ) -> str:
        self._purge_expired()
        token = secrets.token_urlsafe(32)
        while token in self._entries:
            token = secrets.token_urlsafe(32)
        self._entries[token] = _CacheEntry(
            snapshot=snapshot,
            magnet_uri=magnet_uri,
            download_url=download_url,
            expires_at=self._clock() + self._ttl,
        )
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return token

    def get(self, token: str) -> _CacheEntry:
        entry = self._entries.get(token)
        if entry is None or entry.expires_at <= self._clock():
            self._entries.pop(token, None)
            raise ExpiredSearchToken
        self._entries.move_to_end(token)
        return entry

    def take(self, token: str) -> _CacheEntry:
        entry = self.get(token)
        del self._entries[token]
        return entry

    def _purge_expired(self) -> None:
        now = self._clock()
        expired = [token for token, entry in self._entries.items() if entry.expires_at <= now]
        for token in expired:
            del self._entries[token]


class ProwlarrAdapter:
    """Search Prowlarr and resolve a user-selected torrent without persistence."""

    def __init__(self, transport: ProwlarrTransport, cache: SearchResultCache) -> None:
        self._transport = transport
        self._cache = cache

    def search(
        self, query: str, filters: Mapping[str, str] | None = None
    ) -> list[ReleaseSearchResult]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("release_search_query_required")
        raw_results = self._transport.search(cleaned_query, dict(filters or {}))
        results: list[ReleaseSearchResult] = []
        for raw in raw_results:
            if str(raw.get("protocol", "")).casefold() != "torrent":
                continue
            magnet = _string(raw.get("magnetUrl"))
            download_url = _string(raw.get("downloadUrl"))
            if not magnet and not download_url:
                continue
            snapshot = _snapshot(raw)
            token = self._cache.put(snapshot, magnet_uri=magnet, download_url=download_url)
            results.append(
                ReleaseSearchResult(
                    token=token,
                    title=snapshot.title,
                    indexer=snapshot.indexer,
                    snapshot=snapshot,
                )
            )
        return results

    def inspect(self, token: str) -> ReleaseSnapshot:
        return self._cache.get(token).snapshot

    def resolve(self, token: str) -> ResolvedRelease:
        entry = self._cache.take(token)
        if entry.magnet_uri:
            artifact: DownloadArtifact = MagnetArtifact(uri=entry.magnet_uri)
        elif entry.download_url:
            artifact = TorrentArtifact(content=self._transport.fetch_torrent(entry.download_url))
        else:  # Defensive: put() is private to this adapter's validated search path.
            raise ExpiredSearchToken
        return ResolvedRelease(snapshot=entry.snapshot, artifact=artifact)


def _snapshot(raw: Mapping[str, object]) -> ReleaseSnapshot:
    guid_value = _string(raw.get("guid"))
    guid = (
        guid_value
        if raw.get("guidIsPublic") is True
        and guid_value is not None
        and SAFE_GUID.fullmatch(guid_value)
        else None
    )
    hash_value = _string(raw.get("infoHash"))
    infohash = hash_value.casefold() if hash_value and INFOHASH.fullmatch(hash_value) else None
    source_page_url = _sanitize_public_page(
        _string(raw.get("infoUrl")),
        normalized_path=_string(raw.get("normalizedPublicPath")),
        path_is_public=raw.get("publicRoutePath") is True,
    )
    return ReleaseSnapshot(
        title=(_string(raw.get("title")) or "Untitled release")[:1000],
        indexer=(_string(raw.get("indexer")) or "Unknown indexer")[:300],
        guid=guid,
        infohash=infohash,
        source_page_url=source_page_url,
    )


def _sanitize_public_page(
    value: str | None, *, normalized_path: str | None, path_is_public: bool
) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host or not _public_host(host):
            return None
        port = parsed.port
    except ValueError:
        return None
    netloc = f"{host}:{port}" if port is not None else host
    origin = urlunsplit((parsed.scheme, netloc, "", "", ""))
    if not path_is_public or not normalized_path:
        return origin
    segments = [segment for segment in normalized_path.split("/") if segment]
    if any(
        segment.casefold() in DOWNLOAD_ROUTE_SEGMENTS
        or any(marker in segment.casefold() for marker in SECRET_MARKERS)
        for segment in segments
    ):
        return None
    if not normalized_path.startswith("/") or any(
        segment in {".", ".."} or SUSPECT_SECRET_SEGMENT.fullmatch(segment) for segment in segments
    ):
        return origin
    return urlunsplit((parsed.scheme, netloc, normalized_path, "", ""))


def _public_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return address.is_global


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
