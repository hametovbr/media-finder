"""qBittorrent Web API transport owned by one module instance."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx
from media_finder_sdk import ModuleError, ModuleFailureCategory, ResolvedModuleEnvironment

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
_SECRET_MARKERS = ("credential", "passkey", "secret", "session", "token")


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
        response = self._client.post(
            self._url("/api/v2/auth/login"),
            data={"username": self._username, "password": self._password},
            follow_redirects=False,
        )
        if response.is_redirect:
            raise RuntimeError
        response.raise_for_status()
        if response.text.strip() != "Ok.":
            raise RuntimeError

    def list_categories(self) -> dict[str, str]:
        response = self._client.get(
            self._url("/api/v2/torrents/categories"),
            follow_redirects=False,
        )
        if response.is_redirect:
            raise RuntimeError
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError
        return {
            str(name): str(details.get("savePath", ""))
            for name, details in payload.items()
            if isinstance(details, dict)
        }

    def add_magnet(self, uri: str, category: str, correlation: str) -> None:
        response = self._client.post(
            self._url("/api/v2/torrents/add"),
            data={"urls": uri, "category": category, "tags": correlation},
            follow_redirects=False,
        )
        self._require_accepted(response)

    def add_torrent(self, content: bytes, category: str, correlation: str) -> None:
        response = self._client.post(
            self._url("/api/v2/torrents/add"),
            data={"category": category, "tags": correlation},
            files={"torrents": ("release.torrent", content, "application/x-bittorrent")},
            follow_redirects=False,
        )
        self._require_accepted(response)

    def find_by_tag(self, correlation: str) -> list[dict[str, str]]:
        response = self._client.get(
            self._url("/api/v2/torrents/info"),
            params={"tag": correlation},
            follow_redirects=False,
        )
        if response.is_redirect:
            raise RuntimeError
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
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

    @staticmethod
    def _require_accepted(response: httpx.Response) -> None:
        if response.is_redirect:
            raise RuntimeError
        response.raise_for_status()
        if response.text.strip() not in {"", "Ok."}:
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


__all__: list[str] = []
