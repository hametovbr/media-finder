"""qBittorrent download-client capability."""

from __future__ import annotations

import httpx
from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    MagnetArtifact,
    ModuleError,
    ModuleFailureCategory,
    SubmissionResult,
    TorrentArtifact,
)

from .transport import QbittorrentTransport


class QbittorrentClient:
    def __init__(self, transport: QbittorrentTransport) -> None:
        self._transport = transport
        self._closed = False

    def validate(self) -> None:
        self._require_open()
        self._authenticate()

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        self._require_open()
        self._authenticate()
        try:
            categories = self._transport.list_categories()
        except Exception:
            raise _error(
                ModuleFailureCategory.UNAVAILABLE,
                "download_client_destinations_unavailable",
            ) from None
        return tuple(
            DownloadDestination(key=category, label=category)
            for category in sorted(categories)
            if category
        )

    def submit(
        self,
        artifact: DownloadArtifact,
        destination: str,
        correlation: str,
    ) -> SubmissionResult:
        self._require_open()
        self._authenticate()
        try:
            categories = self._transport.list_categories()
        except Exception:
            raise _error(
                ModuleFailureCategory.UNAVAILABLE,
                "download_client_destinations_unavailable",
            ) from None
        if destination not in categories:
            raise _error(
                ModuleFailureCategory.INVALID_REQUEST,
                "download_destination_unavailable",
            )
        try:
            if isinstance(artifact, MagnetArtifact):
                self._transport.add_magnet(artifact.uri, destination, correlation)
            elif isinstance(artifact, TorrentArtifact):
                self._transport.add_torrent(artifact.content(), destination, correlation)
            else:  # pragma: no cover - SDK union is closed
                raise _error(
                    ModuleFailureCategory.UNSUPPORTED,
                    "download_artifact_unsupported",
                )
        except ModuleError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise _error(ModuleFailureCategory.TIMEOUT, "submission_timeout") from None
        except Exception:
            raise _error(
                ModuleFailureCategory.UNAVAILABLE,
                "download_client_submission_failed",
            ) from None
        return SubmissionResult(accepted=True, correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        self._require_open()
        self._authenticate()
        try:
            matches = self._transport.find_by_tag(correlation)
        except Exception:
            raise _error(
                ModuleFailureCategory.INCONCLUSIVE,
                "correlation_lookup_inconclusive",
            ) from None
        exact = [
            match
            for match in matches
            if correlation
            in {tag.strip() for tag in match.get("tags", "").split(",") if tag.strip()}
        ]
        return CorrelationResult(
            found=bool(exact),
            correlation=correlation,
            external_task_id=exact[0].get("hash") if exact else None,
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transport.close()

    def _authenticate(self) -> None:
        try:
            self._transport.authenticate()
        except Exception:
            raise _error(
                ModuleFailureCategory.CONFIGURATION,
                "download_client_authentication_failed",
            ) from None

    def _require_open(self) -> None:
        if self._closed:
            raise _error(
                ModuleFailureCategory.UNAVAILABLE,
                "download_client_closed",
            )


def _error(category: ModuleFailureCategory, code: str) -> ModuleError:
    return ModuleError(category=category, code=code)


__all__: list[str] = []
