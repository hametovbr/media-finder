import asyncio
from datetime import UTC, datetime

import pytest
from catalog_fixtures import CatalogFixture as CatalogService
from catalog_fixtures import RevisionInput
from gateway_fixtures import create_gateway
from media_finder_control import ControlFailure, Locale
from media_finder_control.models import MetadataSearchRequest, MetadataSelectionRequest
from media_finder_core.catalog.persistence import (
    MediaItemRecord as MediaItem,
)
from media_finder_core.catalog.persistence import (
    MetadataRevisionRecord as MetadataRevision,
)
from media_finder_core.platform import EphemeralCache
from media_finder_sdk import MediaKind, NormalizedMetadata, Provenance
from media_finder_server.control_gateway import BackendControlGateway
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _gateway(database: Session, fake_provider) -> BackendControlGateway:
    return create_gateway(database, metadata_provider=fake_provider)


def _add_item(
    database: Session,
    *,
    provider: str,
    external_id: str,
    title: str,
    year: int | None = 2025,
) -> MediaItem:
    catalog = CatalogService(database)
    item, _ = catalog.get_or_create_item(provider, external_id, MediaKind.MOVIE)
    catalog.add_revision(
        item,
        RevisionInput.from_normalized(
            NormalizedMetadata(
                kind=MediaKind.MOVIE,
                titles={"en": title},
                year=year,
                provenance=Provenance(
                    provider_id=provider,
                    external_id=external_id,
                    locale="en",
                    fetched_at=datetime(2025, 1, 1, tzinfo=UTC),
                ),
            )
        ),
    )
    return item


def test_metadata_search_uses_requested_locale_and_selection_is_one_use(
    database: Session, fake_provider
) -> None:
    selections = EphemeralCache()
    gateway = create_gateway(
        database,
        metadata_provider=fake_provider,
        metadata_selections=selections,
    )

    async def scenario() -> None:
        results = await gateway.search_metadata(
            request=MetadataSearchRequest(query="Localized", locale=Locale.RU)
        )
        assert len(results) == 1
        assert results[0].locale is Locale.RU
        assert results[0].description == "Fixture search preview"
        assert str(results[0].poster_url) == "https://images.example.test/posters/fixture-1.jpg"
        retained = selections.get(results[0].token)
        assert retained.description == results[0].description
        assert retained.poster_url == results[0].poster_url
        saved = await gateway.select_metadata(
            token=results[0].token,
            request=MetadataSelectionRequest(),
            locale=Locale.RU,
        )
        assert saved.item.provider_key == fake_provider.manifest.module_id
        assert saved.item.metadata.titles == {"ru": "Fixture"}
        serialized = saved.item.metadata.model_dump(mode="json")
        assert "description" not in serialized
        assert "poster_url" not in serialized
        assert saved.created is True

        with pytest.raises(ControlFailure) as consumed:
            await gateway.select_metadata(
                token=results[0].token,
                request=MetadataSelectionRequest(),
                locale=Locale.RU,
            )
        assert consumed.value.status == 410
        assert consumed.value.error.code == "selection_expired"

    asyncio.run(scenario())


def test_exact_duplicate_returns_existing_without_new_revision(
    database: Session, fake_provider
) -> None:
    existing = _add_item(
        database,
        provider=fake_provider.manifest.module_id,
        external_id="1",
        title="Fixture",
    )
    gateway = _gateway(database, fake_provider)

    async def scenario() -> None:
        result = (
            await gateway.search_metadata(
                request=MetadataSearchRequest(query="Fixture", locale=Locale.EN)
            )
        )[0]
        selected = await gateway.select_metadata(
            token=result.token,
            request=MetadataSelectionRequest(),
            locale=Locale.EN,
        )
        assert selected.item.id == existing.id
        assert selected.created is False

    asyncio.run(scenario())
    assert database.scalar(select(func.count(MetadataRevision.id))) == 1


def test_cross_provider_similarity_requires_new_confirmation_token(
    database: Session, fake_provider
) -> None:
    _add_item(database, provider="other", external_id="other-1", title="Fixture", year=None)
    gateway = _gateway(database, fake_provider)

    async def scenario() -> None:
        result = (
            await gateway.search_metadata(
                request=MetadataSearchRequest(query="Fixture", locale=Locale.EN)
            )
        )[0]
        with pytest.raises(ControlFailure) as warning:
            await gateway.select_metadata(
                token=result.token,
                request=MetadataSelectionRequest(),
                locale=Locale.EN,
            )
        assert warning.value.status == 409
        assert warning.value.error.code == "confirmation_required"
        confirmation = warning.value.error.details["confirmation_token"]
        assert isinstance(confirmation, str)
        assert (
            database.scalar(
                select(func.count(MediaItem.id)).where(
                    MediaItem.provider_key == fake_provider.manifest.module_id
                )
            )
            == 0
        )

        saved = await gateway.select_metadata(
            token=confirmation,
            request=MetadataSelectionRequest(confirm_similarity=True),
            locale=Locale.EN,
        )
        assert saved.item.provider_key == fake_provider.manifest.module_id
        assert (
            database.scalar(
                select(func.count(MetadataRevision.id)).where(
                    MetadataRevision.media_item_id == saved.item.id
                )
            )
            == 1
        )

    asyncio.run(scenario())
