"""Prowlarr torrent release capability."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from media_finder_sdk import (
    DownloadArtifact,
    MagnetArtifact,
    ModuleError,
    ModuleFailureCategory,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    TorrentArtifact,
    is_safe_public_source_page,
    is_safe_release_guid,
)
from pydantic import HttpUrl

from .transport import ProwlarrTransport

_INFOHASH = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})$")


class ProwlarrProvider:
    def __init__(self, transport: ProwlarrTransport) -> None:
        self._transport = transport
        self._closed = False

    def validate(self) -> None:
        self._require_open()
        self._transport.validate()

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        self._require_open()
        filters = _filters(query)
        raw_results = self._transport.search(query.query.strip(), filters)
        candidates: list[ReleaseCandidate] = []
        for raw in raw_results:
            if str(raw.get("protocol", "")).casefold() != "torrent":
                continue
            magnet = _string(raw.get("magnetUrl"))
            download_url = _string(raw.get("downloadUrl"))
            if magnet is None and download_url is None:
                continue
            snapshot = _snapshot(raw)
            selection = PrivateReleaseSelection.from_bytes(
                json.dumps(
                    {"magnet": magnet, "download_url": download_url},
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            )
            candidates.append(ReleaseCandidate(snapshot=snapshot, selection=selection))
            if len(candidates) >= query.limit:
                break
        return tuple(candidates)

    def resolve(self, selection: PrivateReleaseSelection) -> DownloadArtifact:
        self._require_open()
        try:
            value = json.loads(selection.payload())
            if not isinstance(value, dict) or set(value) != {"download_url", "magnet"}:
                raise ValueError
            magnet = value["magnet"]
            download_url = value["download_url"]
            if magnet is not None:
                if not isinstance(magnet, str):
                    raise ValueError
                return MagnetArtifact(uri=magnet)
            if not isinstance(download_url, str):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_REQUEST,
                code="release_selection_invalid",
            ) from None
        return TorrentArtifact.from_bytes(self._transport.fetch_torrent(download_url))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transport.close()

    def _require_open(self) -> None:
        if self._closed:
            raise ModuleError(
                category=ModuleFailureCategory.UNAVAILABLE,
                code="release_provider_closed",
            )


def _filters(query: ReleaseSearchQuery) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for item in query.filters:
        key = {"indexer-ids": "indexerIds"}.get(item.key, item.key)
        mapped[key] = ",".join(item.values)
    return mapped


def _snapshot(raw: Mapping[str, object]) -> SafeReleaseSnapshot:
    guid_value = _string(raw.get("guid"))
    guid = guid_value if guid_value and is_safe_release_guid(guid_value) else None
    hash_value = _string(raw.get("infoHash"))
    infohash = hash_value.casefold() if hash_value and _INFOHASH.fullmatch(hash_value) else None
    return SafeReleaseSnapshot(
        title=(_string(raw.get("title")) or "Untitled release")[:1000],
        indexer=(_string(raw.get("indexer")) or "Unknown indexer")[:300],
        guid=guid,
        infohash=infohash,
        source_page_url=(
            HttpUrl(safe_page)
            if (safe_page := _safe_public_page(_string(raw.get("infoUrl")))) is not None
            else None
        ),
    )


def _safe_public_page(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    safe_page = urlunsplit((parsed.scheme, netloc, "/", "", ""))
    return safe_page if is_safe_public_source_page(safe_page) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__: list[str] = []
