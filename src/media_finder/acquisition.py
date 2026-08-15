"""User-driven torrent handoff with bounded acquisition state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from media_finder_sdk import MagnetArtifact as SDKMagnetArtifact
from media_finder_sdk import ModuleError as SDKModuleError
from media_finder_sdk import TorrentArtifact as SDKTorrentArtifact
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Acquisition, DownloadClientInstance, MediaItem, MetadataRevision
from .release_selection import ReleaseSelectionExpired, ReleaseSelectionService
from .sdk.errors import ModuleError
from .sdk.protocols import DownloadClient
from .sdk.types import DownloadArtifact, DownloadDestination, MagnetArtifact, TorrentArtifact
from .system_clients import SYSTEM_QBITTORRENT_ID


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    media_item_id: str
    metadata_revision_id: str
    client_instance_id: str
    destination: str
    release_token: str
    idempotency_key: str


class DestinationUnavailable(ValueError):
    def __init__(self, current_destinations: list[DownloadDestination]) -> None:
        super().__init__("download_destination_unavailable")
        self.current_destinations = tuple(current_destinations)


ClientLoader = Callable[[DownloadClientInstance], DownloadClient]


class AcquisitionService:
    def __init__(
        self,
        session: Session,
        releases: ReleaseSelectionService | None,
        client_loader: ClientLoader,
    ) -> None:
        self._session = session
        self._releases = releases
        self._client_loader = client_loader

    def submit(self, request: AcquisitionRequest) -> Acquisition:
        existing = self._by_idempotency(request.idempotency_key)
        if existing is not None:
            return existing
        if request.client_instance_id != SYSTEM_QBITTORRENT_ID:
            raise ValueError("download_client_system_required")
        if self._releases is None:
            raise ValueError("acquisition_unavailable")

        revision = self._session.get(MetadataRevision, request.metadata_revision_id)
        item = self._session.get(MediaItem, request.media_item_id)
        instance = self._session.get(DownloadClientInstance, request.client_instance_id)
        if revision is None or item is None or instance is None:
            raise ValueError("acquisition_reference_not_found")
        if instance.archived_at is not None:
            raise ValueError("download_client_archived")
        if not instance.system_owned or instance.module_key != "qbittorrent":
            raise ValueError("download_client_system_required")
        if revision.media_item_id != item.id:
            raise ValueError("acquisition_revision_mismatch")

        client = self._client_loader(instance)
        destinations = client.list_destinations()
        if request.destination not in {destination.key for destination in destinations}:
            raise DestinationUnavailable(destinations)

        snapshot = self._releases.inspect(request.release_token)
        acquisition = Acquisition(
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            download_client_instance_id=instance.id,
            idempotency_key=request.idempotency_key,
            naming_profile="jellyfin-v1",
            status="pending",
            destination=request.destination,
            release_title=snapshot.title,
            indexer=snapshot.indexer,
            guid=snapshot.guid,
            infohash=snapshot.infohash,
            source_page_url=(
                str(snapshot.source_page_url) if snapshot.source_page_url is not None else None
            ),
        )
        self._session.add(acquisition)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            duplicate = self._by_idempotency(request.idempotency_key)
            if duplicate is None:
                raise
            return duplicate

        correlation = f"mf-acq-{acquisition.id}"
        try:
            resolved = self._releases.resolve(request.release_token)
            result = client.submit(
                _legacy_artifact(resolved.artifact), request.destination, correlation
            )
        except ReleaseSelectionExpired:
            return self._transition(acquisition, "failed", "release_search_token_expired")
        except (ModuleError, SDKModuleError) as error:
            if error.code == "submission_timeout":
                return self._resolve_timeout(acquisition, client, correlation)
            return self._transition(acquisition, "failed", _safe_code(error.code))
        except Exception:
            return self._transition(acquisition, "failed", "download_client_submission_failed")

        if result.correlation != correlation:
            return self._transition(acquisition, "failed", "download_client_correlation_mismatch")
        if not result.accepted:
            return self._transition(acquisition, "failed", "download_client_rejected")
        acquisition.external_task_id = result.external_task_id
        return self._transition(acquisition, "submitted")

    def reconcile(self, acquisition_id: str) -> Acquisition:
        try:
            identity = UUID(acquisition_id)
        except ValueError as error:
            raise ValueError("acquisition_not_found") from error
        acquisition = self._session.get(Acquisition, identity)
        if acquisition is None:
            raise ValueError("acquisition_not_found")
        if acquisition.status != "pending":
            return acquisition
        instance = cast(DownloadClientInstance, acquisition.download_client_instance)
        if (
            instance.id != SYSTEM_QBITTORRENT_ID
            or not instance.system_owned
            or instance.archived_at is not None
        ):
            raise ValueError("download_client_system_required")
        client = self._client_loader(instance)
        return self._reconcile_lookup(
            acquisition, client, f"mf-acq-{acquisition.id}", absent_is_failure=False
        )

    def pending_after_startup(self) -> list[Acquisition]:
        """Expose pending rows for manual reconciliation; never submit them."""

        return list(
            self._session.scalars(select(Acquisition).where(Acquisition.status == "pending"))
        )

    def _resolve_timeout(
        self, acquisition: Acquisition, client: DownloadClient, correlation: str
    ) -> Acquisition:
        return self._reconcile_lookup(acquisition, client, correlation, absent_is_failure=True)

    def _reconcile_lookup(
        self,
        acquisition: Acquisition,
        client: DownloadClient,
        correlation: str,
        *,
        absent_is_failure: bool,
    ) -> Acquisition:
        try:
            result = client.find_by_correlation(correlation)
        except ModuleError:
            return acquisition
        except Exception:
            return acquisition
        if result.correlation != correlation or not result.conclusive:
            return acquisition
        if result.found:
            acquisition.external_task_id = result.external_task_id
            return self._transition(acquisition, "submitted")
        if absent_is_failure:
            return self._transition(acquisition, "failed", "submission_timeout_not_found")
        return self._transition(acquisition, "failed", "manual_reconcile_not_found")

    def _by_idempotency(self, key: str) -> Acquisition | None:
        return self._session.scalar(select(Acquisition).where(Acquisition.idempotency_key == key))

    def _transition(
        self, acquisition: Acquisition, status: str, failure_code: str | None = None
    ) -> Acquisition:
        acquisition.status = status
        acquisition.failure_code = failure_code
        acquisition.updated_at = datetime.now(UTC)
        self._session.commit()
        return acquisition


def _safe_code(code: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not code or len(code) > 200 or any(character not in allowed for character in code):
        return "download_client_submission_failed"
    return code


def _legacy_artifact(artifact: SDKMagnetArtifact | SDKTorrentArtifact) -> DownloadArtifact:
    if isinstance(artifact, SDKMagnetArtifact):
        return MagnetArtifact(uri=artifact.uri)
    return TorrentArtifact(content=artifact.content())
