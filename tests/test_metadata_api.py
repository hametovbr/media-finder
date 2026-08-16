from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from media_finder.api import create_app
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Acquisition
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance, RetentionPolicy
from media_finder_core.catalog.persistence import SqlAlchemyCatalogRepository
from media_finder_core.platform.database import create_database, migrate_to_head, session_factory


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer integration-secret"}


def _metadata(
    title: str, provider: str = "manual", external_id: str = "fixture"
) -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en-US": title, "ja-JP": "千と千尋の神隠し"},
        original_title="千と千尋の神隠し",
        year=2001,
        plot="A journey <beyond> & home.",
        release_date="2001-07-20",
        runtime_minutes=125,
        provider_ids={provider: external_id},
        genres=("Animation",),
        tags=("coming-of-age",),
        countries=("Japan",),
        studios=("Studio Ghibli",),
        provenance=Provenance(
            provider_key=provider,
            external_id=external_id,
            locale="en-US",
            source_label="Fixture",
        ),
        completeness=0.95,
        structural_quality=1.0,
    )


def test_metadata_endpoints_return_current_and_pinned_validated_snapshots(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'metadata.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    with session_factory(engine)() as session:
        service = CatalogService(session)
        item = service.create_manual_item(_metadata("Pinned title"))
        pinned = item.current_revision
        assert pinned is not None
        acquisition = Acquisition(
            id=(acquisition_identity := uuid4()),
            correlation=f"mf-acq-{acquisition_identity}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="fixture-download",
            download_client_module_version="1.0.0",
            media_item_id=item.id,
            metadata_revision_id=pinned.id,
            idempotency_key="metadata-pin",
            naming_profile="jellyfin-v1",
            status="submitted",
        )
        session.add(acquisition)
        session.commit()
        service.add_revision(item, RevisionInput.from_normalized(_metadata("Current title")))
        item_id, acquisition_id = item.id, str(acquisition.id)
    engine.dispose()

    client = TestClient(create_app(url, integration_token="integration-secret"))
    current = client.get(f"/api/v1/media-items/{item_id}/metadata", headers=_headers())
    pinned_response = client.get(
        f"/api/v1/acquisitions/{acquisition_id}/metadata", headers=_headers()
    )

    assert current.status_code == pinned_response.status_code == 200
    assert current.json()["titles"]["en-US"] == "Current title"
    assert pinned_response.json()["titles"]["en-US"] == "Pinned title"
    for payload in (current.json(), pinned_response.json()):
        assert payload["schema_version"] == "1"
        assert payload["provenance"]["locale"] == "en-US"
        assert payload["completeness"] == 0.95
        assert payload["structural_quality"] == 1.0
        assert "raw_payload" not in payload
        assert "effective_payload" not in payload


def test_expiry_is_enforced_at_boundary_before_and_after_purge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'expiry.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    expiry = datetime(2025, 6, 1, 12, tzinfo=UTC)
    with session_factory(engine)() as session:
        service = CatalogService(session)
        item, _ = service.get_or_create_item("fixture-provider", "42", "movie")
        revision = service.add_provider_revision(
            item,
            {"secret_provider_field": "must-never-escape"},
            _metadata("Expiring", "fixture-provider", "42"),
            {},
            RetentionPolicy(expires_at=expiry),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        acquisition = Acquisition(
            id=(acquisition_identity := uuid4()),
            correlation=f"mf-acq-{acquisition_identity}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="fixture-download",
            download_client_module_version="1.0.0",
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            idempotency_key="expired-pin",
            naming_profile="jellyfin-v1",
            status="submitted",
        )
        session.add(acquisition)
        session.commit()
        item_id, acquisition_id, revision_id = item.id, str(acquisition.id), revision.id
    engine.dispose()

    client = TestClient(
        create_app(
            url,
            integration_token="integration-secret",
            clock=lambda: expiry,
        )
    )
    for resource in (
        f"/api/v1/media-items/{item_id}/metadata",
        f"/api/v1/acquisitions/{acquisition_id}/metadata",
    ):
        response = client.get(resource, headers=_headers())
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "metadata_source_expired"
        assert "must-never-escape" not in response.text

    engine = create_database(url)
    with session_factory(engine)() as session:
        SqlAlchemyCatalogRepository(session).purge_revision(revision_id, expiry)
        session.commit()
    engine.dispose()

    purged = client.get(f"/api/v1/acquisitions/{acquisition_id}/metadata", headers=_headers())
    assert purged.status_code == 410
    assert purged.json()["error"]["code"] == "metadata_source_expired"


def test_naming_and_nfo_expiry_at_boundary_and_after_purge_for_current_and_pinned(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'export-expiry.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    expiry = datetime(2025, 6, 1, 12, tzinfo=UTC)
    with session_factory(engine)() as session:
        service = CatalogService(session)
        item, _ = service.get_or_create_item("fixture-provider", "export-42", "movie")
        revision = service.add_provider_revision(
            item,
            {"private": "provider-only"},
            _metadata("Expiring exports", "fixture-provider", "export-42"),
            {},
            RetentionPolicy(expires_at=expiry),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        acquisition = Acquisition(
            id=(acquisition_identity := uuid4()),
            correlation=f"mf-acq-{acquisition_identity}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="fixture-download",
            download_client_module_version="1.0.0",
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            idempotency_key="export-expiry",
            naming_profile="jellyfin-v1",
            status="submitted",
        )
        session.add(acquisition)
        session.commit()
        item_id, acquisition_id, revision_id = item.id, str(acquisition.id), revision.id
    engine.dispose()
    client = TestClient(
        create_app(
            url,
            integration_token="integration-secret",
            clock=lambda: expiry,
        )
    )
    resources = (
        (f"/api/v1/media-items/{item_id}/exports/naming", {"entity_type": "movie"}),
        (f"/api/v1/acquisitions/{acquisition_id}/exports/naming", {"entity_type": "movie"}),
        (f"/api/v1/media-items/{item_id}/exports/nfo", {"entity_type": "movie"}),
        (f"/api/v1/acquisitions/{acquisition_id}/exports/nfo", {"entity_type": "movie"}),
    )

    for resource, params in resources:
        response = client.get(resource, headers=_headers(), params=params)
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "metadata_source_expired"

    engine = create_database(url)
    with session_factory(engine)() as session:
        SqlAlchemyCatalogRepository(session).purge_revision(revision_id, expiry)
        session.commit()
    engine.dispose()

    for resource, params in resources:
        response = client.get(resource, headers=_headers(), params=params)
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "metadata_source_expired"
