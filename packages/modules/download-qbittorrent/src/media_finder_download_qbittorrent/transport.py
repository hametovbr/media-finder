"""qBittorrent Web API transport owned by one module instance."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import httpx
from media_finder_sdk import ModuleError, ModuleFailureCategory, ResolvedModuleEnvironment

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
_SECRET_MARKERS = ("credential", "passkey", "secret", "session", "token")
_MAX_ACK_RESPONSE_BYTES = 4096
_MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RESULTS = 1000


class QbittorrentTransport:
    def __init__(
        self,
        *,
        environment: ResolvedModuleEnvironment,
        client: httpx.Client,
    ) -> None:
        try:
            self._base_url = _validated_base_url(environment.require("QBITTORRENT_URL"))
        except ValueError:
            raise _error(
                ModuleFailureCategory.CONFIGURATION,
                "qbittorrent_configuration_invalid",
            ) from None
        self._username = environment.require("QBITTORRENT_USERNAME")
        self._password = environment.require("QBITTORRENT_PASSWORD")
        self._client = client
        self._closed = False

    def authenticate(self) -> None:
        response_text = self._post_text(
            "/api/v2/auth/login",
            data={"username": self._username, "password": self._password},
        )
        if response_text.strip() != "Ok.":
            raise RuntimeError

    def list_categories(self) -> dict[str, str]:
        payload = self._get_json("/api/v2/torrents/categories")
        if not isinstance(payload, dict) or len(payload) > _MAX_RESULTS:
            raise RuntimeError
        return {
            str(name): str(details.get("savePath", ""))
            for name, details in payload.items()
            if isinstance(details, dict)
        }

    def add_magnet(self, uri: str, category: str, correlation: str) -> None:
        response_text = self._post_text(
            "/api/v2/torrents/add",
            data={"urls": uri, "category": category, "tags": correlation},
        )
        self._require_accepted(response_text)

    def add_torrent(self, content: bytes, category: str, correlation: str) -> None:
        response_text = self._post_text(
            "/api/v2/torrents/add",
            data={"category": category, "tags": correlation},
            files={"torrents": ("release.torrent", content, "application/x-bittorrent")},
        )
        self._require_accepted(response_text)

    def find_by_tag(self, correlation: str) -> list[dict[str, str]]:
        payload = self._get_json("/api/v2/torrents/info", params={"tag": correlation})
        if not isinstance(payload, list) or len(payload) > _MAX_RESULTS:
            raise RuntimeError
        return [
            {"hash": str(item.get("hash", "")), "tags": str(item.get("tags", ""))}
            for item in payload
            if isinstance(item, dict)
        ]

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _get_json(self, path: str, *, params: dict[str, str] | None = None) -> object:
        with self._client.stream(
            "GET",
            self._url(path),
            params=params,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise RuntimeError
            response.raise_for_status()
            content = _read_bounded(response, _MAX_JSON_RESPONSE_BYTES)
        try:
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError from None

    def _post_text(
        self,
        path: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> str:
        with self._client.stream(
            "POST",
            self._url(path),
            data=data,
            files=files,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                raise RuntimeError
            response.raise_for_status()
            content = _read_bounded(response, _MAX_ACK_RESPONSE_BYTES)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            raise RuntimeError from None

    @staticmethod
    def _require_accepted(response_text: str) -> None:
        if response_text.strip() not in {"", "Ok."}:
            raise RuntimeError

    def __repr__(self) -> str:
        return "QbittorrentTransport(credentials=<redacted>)"


def _validated_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        path = parsed.path or ""
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or _SAFE_PATH.fullmatch(path or "/") is None
            or "%" in path
            or "\\" in path
            or any(
                marker in segment.casefold()
                for segment in path.split("/")
                for marker in _SECRET_MARKERS
            )
        ):
            raise ValueError
        _ = parsed.port
    except (UnicodeError, ValueError):
        raise ValueError("qbittorrent_configuration_invalid") from None
    return value.rstrip("/")


def _error(category: ModuleFailureCategory, code: str) -> ModuleError:
    return ModuleError(category=category, code=code)


def _read_bounded(response: httpx.Response, limit: int) -> bytes:
    declared = response.headers.get("content-length")
    try:
        if declared is not None and int(declared) > limit:
            raise RuntimeError
    except ValueError:
        raise RuntimeError from None
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise RuntimeError
        chunks.append(chunk)
    return b"".join(chunks)


__all__: list[str] = []
