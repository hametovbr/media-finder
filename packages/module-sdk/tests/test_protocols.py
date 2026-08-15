"""Specialized synchronous module capability contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import media_finder_sdk
import pytest
from media_finder_sdk import (
    DownloadClient,
    MediaKind,
    MetadataIdentity,
    MetadataProvider,
    MetadataRetentionPolicy,
    NormalizedMetadata,
    PrivateReleaseSelection,
    Provenance,
    ProviderPayload,
    ReleaseProvider,
    TorrentArtifact,
)
from pydantic import ValidationError


class _MetadataShape:
    def validate(self) -> None: ...

    def search(self, query):  # type: ignore[no-untyped-def]
        return ()

    def fetch(self, identity):  # type: ignore[no-untyped-def]
        return ProviderPayload(data={})

    def normalize(self, payload, identity):  # type: ignore[no-untyped-def]
        return NormalizedMetadata(
            kind=MediaKind.MOVIE,
            titles={"en": "Fixture"},
            provenance=Provenance(
                provider_id="fixture",
                external_id="1",
                locale="en",
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )

    def close(self) -> None: ...


def test_specialized_protocols_are_runtime_checkable_without_universal_module_api() -> None:
    assert isinstance(_MetadataShape(), MetadataProvider)
    assert not isinstance(_MetadataShape(), ReleaseProvider)
    assert not isinstance(_MetadataShape(), DownloadClient)
    assert not isinstance(_MetadataShape(), MetadataRetentionPolicy)

    public_names = set(media_finder_sdk.__all__)
    assert not public_names & {
        "Module",
        "ModuleContext",
        "ModuleHook",
        "lookup_module",
        "register_hook",
    }


def test_private_release_values_are_bounded_redacted_and_not_serializable() -> None:
    selection = PrivateReleaseSelection.from_bytes(b"private-download-url")
    artifact = TorrentArtifact.from_bytes(b"torrent-payload")

    assert selection.payload() == b"private-download-url"
    assert artifact.content() == b"torrent-payload"
    assert "private-download-url" not in repr(selection)
    assert "torrent-payload" not in repr(artifact)
    assert not hasattr(selection, "model_dump")
    with pytest.raises(ValueError, match="release_selection_too_large"):
        PrivateReleaseSelection.from_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="torrent_artifact_too_large"):
        TorrentArtifact.from_bytes(b"x" * (20 * 1024 * 1024 + 1))


def test_metadata_dtos_are_strict_and_deeply_immutable() -> None:
    source_titles = {"en": "Fixture"}
    metadata = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles=source_titles,
        provider_ids={"fixture": "1"},
        provenance=Provenance(provider_id="fixture", external_id="1", locale="en"),
    )
    source_titles["en"] = "Changed"

    assert metadata.titles == {"en": "Fixture"}
    with pytest.raises(TypeError):
        metadata.titles["en"] = "Changed"
    with pytest.raises(ValidationError):
        MetadataIdentity(
            provider_id="fixture",
            external_id="",
            media_kind=MediaKind.MOVIE,
            locale="en",
        )
