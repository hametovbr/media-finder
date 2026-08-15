"""Bounded, path-confined Prowlarr HTTP transport."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from media_finder_sdk import ModuleError, ModuleFailureCategory, ResolvedModuleEnvironment

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
_SECRET_MARKERS = ("credential", "passkey", "secret", "session", "token")
_LOG_URL = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)


class _HttpUrlRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        redacted = _LOG_URL.sub("[REDACTED_URL]", rendered)
        if rendered != redacted:
            record.msg = redacted
            record.args = ()
        return True


def _install_http_redaction() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, _HttpUrlRedactionFilter) for item in logger.filters):
            logger.addFilter(_HttpUrlRedactionFilter())


@dataclass(frozen=True, slots=True)
class ProwlarrLimits:
    max_json_bytes: int = 2 * 1024 * 1024
    max_search_results: int = 1000
    max_torrent_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if min(self.max_json_bytes, self.max_search_results, self.max_torrent_bytes) < 1:
            raise ValueError("prowlarr_limits_invalid")


class ProwlarrTransport:
    def __init__(
        self,
        *,
        environment: ResolvedModuleEnvironment,
        client: httpx.Client,
        limits: ProwlarrLimits,
    ) -> None:
        _install_http_redaction()
        base_url = environment.require("PROWLARR_URL")
        try:
            self._base_url, self._origin, self._base_path = _validated_base_url(base_url)
        except ValueError:
            raise _error(
                ModuleFailureCategory.CONFIGURATION,
                "prowlarr_configuration_invalid",
            ) from None
        self._api_key = environment.require("PROWLARR_API_KEY")
        self._client = client
        self._limits = limits
        self._closed = False

    def validate(self) -> None:
        try:
            response = self._client.get(
                f"{self._base_url}/api/v1/system/status",
                headers=self._headers(),
                follow_redirects=False,
            )
            if response.is_redirect:
                raise RuntimeError
            response.raise_for_status()
        except Exception:
            raise _error(
                ModuleFailureCategory.CONFIGURATION,
                "prowlarr_configuration_invalid",
            ) from None

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        parameters = {"query": query, "type": "search", **filters}
        try:
            with self._client.stream(
                "GET",
                f"{self._base_url}/api/v1/search",
                params=parameters,
                headers=self._headers(),
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    raise RuntimeError
                response.raise_for_status()
                content = _read_bounded(
                    response,
                    self._limits.max_json_bytes,
                    "release_response_too_large",
                )
            payload = json.loads(content)
        except ModuleError:
            raise
        except Exception:
            raise _error(
                ModuleFailureCategory.UNAVAILABLE,
                "release_provider_unavailable",
            ) from None
        if not isinstance(payload, list):
            raise _error(ModuleFailureCategory.UNAVAILABLE, "release_provider_unavailable")
        if len(payload) > self._limits.max_search_results:
            raise _error(
                ModuleFailureCategory.LIMIT_EXCEEDED,
                "release_result_limit_exceeded",
            )
        return [dict(item) for item in payload if isinstance(item, dict)]

    def fetch_torrent(self, url: str) -> bytes:
        if not _within_configured_boundary(url, self._origin, self._base_path):
            raise _error(
                ModuleFailureCategory.REJECTED,
                "release_download_origin_rejected",
            )
        try:
            with self._client.stream(
                "GET",
                url,
                headers=self._headers(),
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    raise RuntimeError
                response.raise_for_status()
                return _read_bounded(
                    response,
                    self._limits.max_torrent_bytes,
                    "release_torrent_too_large",
                )
        except ModuleError:
            raise
        except Exception:
            raise _error(
                ModuleFailureCategory.UNAVAILABLE,
                "release_download_failed",
            ) from None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key}

    def __repr__(self) -> str:
        return f"ProwlarrTransport(base_url={self._base_url!r}, api_key=<redacted>)"


def _error(category: ModuleFailureCategory, code: str) -> ModuleError:
    return ModuleError(category=category, code=code)


def _validated_base_url(value: str) -> tuple[str, tuple[str, str, int], str]:
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
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError):
        raise ValueError("prowlarr_configuration_invalid") from None
    base_path = path.rstrip("/")
    return value.rstrip("/"), (parsed.scheme, parsed.hostname.casefold(), port), base_path


def _within_configured_boundary(
    value: str,
    origin: tuple[str, str, int],
    base_path: str,
) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        candidate_origin = (parsed.scheme, (parsed.hostname or "").casefold(), port)
        path = parsed.path
    except (UnicodeError, ValueError):
        return False
    if (
        candidate_origin != origin
        or parsed.username is not None
        or parsed.password is not None
        or not path.startswith("/")
        or "%" in path
        or "\\" in path
    ):
        return False
    segments = path.removeprefix("/").split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        return False
    return not base_path or path == base_path or path.startswith(f"{base_path}/")


def _read_bounded(response: httpx.Response, limit: int, code: str) -> bytes:
    declared = response.headers.get("content-length")
    try:
        if declared is not None and int(declared) > limit:
            raise _error(ModuleFailureCategory.LIMIT_EXCEEDED, code)
    except ValueError:
        raise _error(ModuleFailureCategory.UNAVAILABLE, "release_response_invalid") from None
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > limit:
            raise _error(ModuleFailureCategory.LIMIT_EXCEEDED, code)
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["ProwlarrLimits"]
