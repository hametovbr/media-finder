"""Statically packaged qBittorrent download-client module."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from ...sdk.errors import ModuleError
from ...sdk.types import (
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    MagnetArtifact,
    ModuleKind,
    ModuleManifest,
    SubmissionResult,
    TorrentArtifact,
)

ENV_REFERENCE = re.compile(r"^env:[A-Z_][A-Z0-9_]*$")
SECRET_VALUE_MARKERS = ("credential", "passkey", "secret", "session", "token")


class QbittorrentTransport(Protocol):
    def authenticate(self, username: str, password: str) -> None: ...
    def list_categories(self) -> dict[str, str]: ...
    def add_magnet(self, uri: str, category: str, tag: str) -> str: ...
    def add_torrent(self, content: bytes, category: str, tag: str) -> str: ...
    def find_by_tag(self, tag: str) -> list[dict[str, str]]: ...


class HttpxQbittorrentTransport:
    """Synchronous qBittorrent Web API transport with no persisted credentials."""

    def __init__(self, base_url: str, client: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    def authenticate(self, username: str, password: str) -> None:
        response = self._client.post(
            self._url("/api/v2/auth/login"),
            data={"username": username, "password": password},
        )
        response.raise_for_status()
        if response.text.strip() != "Ok.":
            raise RuntimeError("qBittorrent authentication rejected")

    def list_categories(self) -> dict[str, str]:
        response = self._client.get(self._url("/api/v2/torrents/categories"))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("qBittorrent categories response is invalid")
        return {
            str(name): str(details.get("savePath", ""))
            for name, details in payload.items()
            if isinstance(details, dict)
        }

    def add_magnet(self, uri: str, category: str, tag: str) -> str:
        response = self._client.post(
            self._url("/api/v2/torrents/add"),
            data={"urls": uri, "category": category, "tags": tag},
        )
        self._require_accepted(response)
        return ""

    def add_torrent(self, content: bytes, category: str, tag: str) -> str:
        response = self._client.post(
            self._url("/api/v2/torrents/add"),
            data={"category": category, "tags": tag},
            files={"torrents": ("release.torrent", content, "application/x-bittorrent")},
        )
        self._require_accepted(response)
        return ""

    def find_by_tag(self, tag: str) -> list[dict[str, str]]:
        response = self._client.get(self._url("/api/v2/torrents/info"), params={"tag": tag})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("qBittorrent torrent response is invalid")
        return [
            {"hash": str(item.get("hash", "")), "tags": str(item.get("tags", ""))}
            for item in payload
            if isinstance(item, dict)
        ]

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    @staticmethod
    def _require_accepted(response: httpx.Response) -> None:
        response.raise_for_status()
        if response.text.strip() not in {"", "Ok."}:
            raise RuntimeError("qBittorrent submission rejected")


class QbittorrentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: Annotated[HttpUrl, Field(title="module.qbittorrent.base_url")]
    username_ref: Annotated[str, Field(title="module.qbittorrent.username_ref")]
    password_ref: Annotated[str, Field(title="module.qbittorrent.password_ref")]

    @field_validator("base_url")
    @classmethod
    def require_non_secret_endpoint(cls, value: HttpUrl) -> HttpUrl:
        secret_path = any(
            marker in segment.casefold()
            for segment in (value.path or "").split("/")
            for marker in SECRET_VALUE_MARKERS
        )
        if value.username or value.password or value.query or value.fragment or secret_path:
            raise ValueError("base URL must not contain credentials, query, or fragment")
        return value

    @field_validator("username_ref", "password_ref")
    @classmethod
    def require_environment_reference(cls, value: str) -> str:
        if ENV_REFERENCE.fullmatch(value) is None:
            raise ValueError("a valid env:NAME reference is required")
        return value


class QbittorrentClient:
    manifest = ModuleManifest(
        key="qbittorrent",
        version="1.0.0",
        contract_version="1",
        name_key="module.qbittorrent.name",
        kind=ModuleKind.DOWNLOAD_CLIENT,
        capabilities=frozenset({"magnet", "torrent", "live_destinations", "correlation"}),
        translation_keys={
            "base_url": "module.qbittorrent.base_url",
            "username_ref": "module.qbittorrent.username_ref",
            "password_ref": "module.qbittorrent.password_ref",
        },
    )
    config_model = QbittorrentConfig

    def __init__(
        self,
        config: QbittorrentConfig,
        transport: QbittorrentTransport,
        secret_resolver: Callable[[str], str],
    ) -> None:
        self._config = config
        self._transport = transport
        self._secret_resolver = secret_resolver

    def validate_config(self) -> None:
        self._authenticate()

    def list_destinations(self) -> list[DownloadDestination]:
        self._authenticate()
        try:
            categories = self._transport.list_categories()
        except Exception:
            raise _safe_error("download_client_destinations_unavailable") from None
        return [
            DownloadDestination(key=category, label=category)
            for category in sorted(categories)
            if category
        ]

    def submit(
        self, artifact: DownloadArtifact, destination: str, correlation: str
    ) -> SubmissionResult:
        self._authenticate()
        try:
            if isinstance(artifact, MagnetArtifact):
                task_id = self._transport.add_magnet(artifact.uri, destination, correlation)
            elif isinstance(artifact, TorrentArtifact):
                task_id = self._transport.add_torrent(artifact.content, destination, correlation)
            else:  # pragma: no cover - the public union is closed
                raise _safe_error("download_artifact_unsupported")
        except ModuleError as error:
            code = (
                "download_artifact_unsupported"
                if error.code == "download_artifact_unsupported"
                else "download_client_submission_failed"
            )
            raise _safe_error(code) from None
        except (TimeoutError, httpx.TimeoutException):
            raise _safe_error("submission_timeout") from None
        except Exception:
            raise _safe_error("download_client_submission_failed") from None
        return SubmissionResult(
            accepted=True, external_task_id=task_id or None, correlation=correlation
        )

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        self._authenticate()
        try:
            matches = self._transport.find_by_tag(correlation)
        except (TimeoutError, httpx.TimeoutException):
            raise _safe_error("correlation_lookup_inconclusive") from None
        except Exception:
            raise _safe_error("correlation_lookup_inconclusive") from None
        exact = [
            match
            for match in matches
            if correlation
            in {tag.strip() for tag in match.get("tags", "").split(",") if tag.strip()}
        ]
        task_id = exact[0].get("hash") if exact else None
        return CorrelationResult(
            found=bool(exact),
            correlation=correlation,
            external_task_id=task_id,
            conclusive=True,
        )

    def _authenticate(self) -> None:
        try:
            username = self._secret_resolver(self._config.username_ref)
            password = self._secret_resolver(self._config.password_ref)
            self._transport.authenticate(username, password)
        except ModuleError:
            raise _safe_error("download_client_authentication_failed") from None
        except Exception:
            raise _safe_error("download_client_authentication_failed") from None


def _safe_error(code: str) -> ModuleError:
    return ModuleError(code=code, message=code)
