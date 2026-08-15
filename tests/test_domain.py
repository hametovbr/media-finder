from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Acquisition, Collection, MediaItem, MetadataRevision
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance, RetentionPolicy
from sqlalchemy.exc import IntegrityError


def metadata(title: str = "Spirited Away", year: int = 2001) -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en": title},
        year=year,
        provenance=Provenance(provider_key="manual", external_id="placeholder", locale="en"),
    )


def test_manual_identity_is_uuid4_and_duplicate_is_returned(database) -> None:
    service = CatalogService(database)
    first = service.create_manual_item(metadata())
    assert UUID(first.external_id).version == 4
    duplicate, created = service.get_or_create_item("manual", first.external_id, MediaKind.MOVIE)
    assert created is False
    assert duplicate.id == first.id


def test_cross_provider_similarity_warns_without_merging(database) -> None:
    service = CatalogService(database)
    manual = service.create_manual_item(metadata())
    other, created = service.get_or_create_item("example", "42", MediaKind.MOVIE)
    service.add_revision(other, RevisionInput.from_normalized(metadata()))
    assert created is True
    assert other.id != manual.id
    assert service.find_similar("Spirited Away", 2001, excluding_provider="example") == [manual]


def test_archive_retains_revisions_and_acquisitions(database) -> None:
    service = CatalogService(database)
    item = service.create_manual_item(metadata())
    revision = item.revisions[-1]
    acquisition = Acquisition(
        id=(acquisition_id := uuid4()),
        correlation=f"mf-acq-{acquisition_id}",
        release_provider_id="fixture-release",
        release_provider_version="1.0.0",
        download_client_module_id="fixture-download",
        download_client_module_version="1.0.0",
        media_item_id=item.id,
        metadata_revision_id=revision.id,
        idempotency_key="archive-test",
        naming_profile="jellyfin-v1",
        status="pending",
    )
    database.add(acquisition)
    service.archive_item(item)
    database.commit()
    assert item.archived_at is not None
    assert database.get(MetadataRevision, revision.id) is not None
    assert database.get(Acquisition, acquisition.id) is not None


def test_revision_envelope_is_immutable(database) -> None:
    service = CatalogService(database)
    item = service.create_manual_item(metadata())
    revision = item.revisions[-1]
    revision.locale = "ru"
    with pytest.raises(ValueError, match="immutable"):
        database.flush()
    database.rollback()
    revision = database.get(MetadataRevision, revision.id)
    revision.effective_payload = {"changed": True}
    with pytest.raises(ValueError, match="immutable"):
        database.flush()


def test_domain_records_are_archive_only(database) -> None:
    service = CatalogService(database)
    item = service.create_manual_item(metadata())
    database.delete(item)
    with pytest.raises(ValueError, match="archive"):
        database.flush()


def test_constraints_identity_collection_archive_and_idempotency(database) -> None:
    database.add_all(
        [
            Collection(name="Kids"),
            Collection(name="Kids"),
        ]
    )
    with pytest.raises(IntegrityError):
        database.commit()


def test_acquisition_pins_revision_and_idempotency_key_is_unique(database) -> None:
    service = CatalogService(database)
    item = service.create_manual_item(metadata())
    pinned = item.revisions[-1]
    first = Acquisition(
        id=(first_id := uuid4()),
        correlation=f"mf-acq-{first_id}",
        release_provider_id="fixture-release",
        release_provider_version="1.0.0",
        download_client_module_id="fixture-download",
        download_client_module_version="1.0.0",
        media_item_id=item.id,
        metadata_revision_id=pinned.id,
        idempotency_key="same-request",
        naming_profile="jellyfin-v1",
        status="pending",
    )
    database.add(first)
    database.commit()
    service.add_revision(item, RevisionInput.from_normalized(metadata("New Title", 2002)))
    assert first.metadata_revision_id == pinned.id
    database.add(
        Acquisition(
            id=(duplicate_id := uuid4()),
            correlation=f"mf-acq-{duplicate_id}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="fixture-download",
            download_client_module_version="1.0.0",
            media_item_id=item.id,
            metadata_revision_id=item.revisions[-1].id,
            idempotency_key="same-request",
            naming_profile="jellyfin-v1",
            status="pending",
        )
    )
    with pytest.raises(IntegrityError):
        database.commit()


def test_acquisition_cannot_be_repointed_to_a_new_revision(database) -> None:
    service = CatalogService(database)
    item = service.create_manual_item(metadata())
    pinned = item.revisions[-1]
    acquisition = Acquisition(
        id=(acquisition_id := uuid4()),
        correlation=f"mf-acq-{acquisition_id}",
        release_provider_id="fixture-release",
        release_provider_version="1.0.0",
        download_client_module_id="fixture-download",
        download_client_module_version="1.0.0",
        media_item_id=item.id,
        metadata_revision_id=pinned.id,
        idempotency_key="immutable-pin",
        naming_profile="jellyfin-v1",
        status="pending",
    )
    database.add(acquisition)
    database.commit()
    replacement = service.add_revision(
        item, RevisionInput.from_normalized(metadata("Replacement", 2002))
    )
    acquisition.metadata_revision_id = replacement.id
    with pytest.raises(ValueError, match="pinned"):
        database.flush()


def test_provider_revision_preserves_raw_and_validates_effective_snapshot(database) -> None:
    service = CatalogService(database)
    item, _ = service.get_or_create_item("tmdb", "129", "movie")
    normalized = metadata()
    normalized = normalized.model_copy(
        update={
            "provenance": normalized.provenance.model_copy(
                update={"provider_key": "tmdb", "external_id": "129"}
            )
        }
    )
    raw = {"id": 129, "overview": "Provider plot", "internal": {"cache": True}}
    revision = service.add_provider_revision(
        item,
        raw,
        normalized,
        {"plot": "User plot"},
        RetentionPolicy(),
        datetime.now(UTC),
    )
    assert revision.raw_payload == raw
    assert revision.effective_payload["plot"] == "User plot"
    with pytest.raises(ValueError, match="override"):
        service.add_provider_revision(
            item,
            raw,
            normalized,
            {"runtime_minutes": "junk"},
            RetentionPolicy(),
            datetime.now(UTC),
        )
    database.rollback()

    item = MediaItem(provider_key="tmdb", external_id="1", kind="movie")
    database.add(item)
    database.commit()
    database.add(MediaItem(provider_key="tmdb", external_id="1", kind="movie"))
    with pytest.raises(IntegrityError):
        database.commit()
