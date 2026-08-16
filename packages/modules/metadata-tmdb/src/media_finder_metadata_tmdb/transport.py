"""Confined HTTP transport for the official TMDB API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from media_finder_sdk import ResolvedModuleEnvironment

OFFICIAL_API_BASE_URL = "https://api.themoviedb.org/3"
_IDENTITY = re.compile(r"^[0-9]{1,20}$")
_ENDPOINT = re.compile(
    r"^/(?:configuration|search/(?:movie|tv)|(?:movie|tv)/[0-9]{1,20}|"
    r"tv/[0-9]{1,20}/season/[0-9]{1,4})$"
)
_MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TmdbEndpoint:
    path: str

    def __post_init__(self) -> None:
        if _ENDPOINT.fullmatch(self.path) is None:
            raise ValueError("tmdb_endpoint_invalid")

    @classmethod
    def configuration(cls) -> TmdbEndpoint:
        return cls("/configuration")

    @classmethod
    def search_movie(cls) -> TmdbEndpoint:
        return cls("/search/movie")

    @classmethod
    def search_series(cls) -> TmdbEndpoint:
        return cls("/search/tv")

    @classmethod
    def movie(cls, external_id: str) -> TmdbEndpoint:
        return cls(f"/movie/{_validated_identity(external_id)}")

    @classmethod
    def series(cls, external_id: str) -> TmdbEndpoint:
        return cls(f"/tv/{_validated_identity(external_id)}")

    @classmethod
    def season(cls, external_id: str, season_number: int) -> TmdbEndpoint:
        identity = _validated_identity(external_id)
        if season_number < 0 or season_number > 9999:
            raise ValueError("metadata_identity_invalid")
        return cls(f"/tv/{identity}/season/{season_number}")


def _validated_identity(value: str) -> str:
    if _IDENTITY.fullmatch(value) is None:
        raise ValueError("metadata_identity_invalid")
    return value


class TmdbTransport:
    """Own one isolated client and never expose the resolved bearer token."""

    def __init__(
        self,
        *,
        environment: ResolvedModuleEnvironment,
        client: httpx.Client,
        base_url: str = OFFICIAL_API_BASE_URL,
    ) -> None:
        if base_url != OFFICIAL_API_BASE_URL:
            raise ValueError("tmdb_base_url_invalid")
        self._token = environment.require("TMDB_TOKEN")
        self._client = client
        self._closed = False

    def get_json(self, endpoint: TmdbEndpoint, params: dict[str, str]) -> dict[str, Any]:
        if not isinstance(endpoint, TmdbEndpoint) or _ENDPOINT.fullmatch(endpoint.path) is None:
            raise ValueError("tmdb_endpoint_invalid")
        with self._client.stream(
            "GET",
            f"{OFFICIAL_API_BASE_URL}{endpoint.path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise RuntimeError("tmdb_redirect_rejected")
            response.raise_for_status()
            content = _read_bounded(response)
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("tmdb_response_invalid") from None
        if not isinstance(payload, dict):
            raise RuntimeError("tmdb_response_invalid")
        return payload

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()

    def __repr__(self) -> str:
        return "TmdbTransport(origin='https://api.themoviedb.org', token=<redacted>)"


def _read_bounded(response: httpx.Response) -> bytes:
    declared = response.headers.get("content-length")
    try:
        if declared is not None and int(declared) > _MAX_JSON_RESPONSE_BYTES:
            raise RuntimeError("tmdb_response_too_large")
    except ValueError:
        raise RuntimeError("tmdb_response_invalid") from None
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > _MAX_JSON_RESPONSE_BYTES:
            raise RuntimeError("tmdb_response_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["TmdbEndpoint", "TmdbTransport"]
