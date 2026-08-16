import asyncio
from datetime import UTC, datetime

import pytest
from media_finder.control_gateway import BackendControlGateway
from media_finder.domain import CatalogService, RevisionInput
from media_finder.integration_runtime import RuntimeResolver
from media_finder.models import MediaItem, MetadataRevision
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder_control import ControlFailure, Locale
from media_finder_control.models import MetadataSearchRequest, MetadataSelectionRequest
from media_finder_core.platform import EphemeralCache
from media_finder_server import create_legacy_module_registry
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

REGISTRY = create_legacy_module_registry()


def _gateway(database: Session, fake_provider) -> BackendControlGateway:
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    runtime = RuntimeResolver(
        providers={fake_provider.manifest.key: fake_provider},
    )
    return BackendControlGateway(
        sessions=sessions,
        cursor_secret=b"cursor-secret-for-tests",
        runtime=runtime,
        metadata_selections=EphemeralCache(),
        registry=REGISTRY,
    )


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
                    provider_key=provider,
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
    gateway = _gateway(database, fake_provider)

    async def scenario() -> None:
        results = await gateway.search_metadata(
            request=MetadataSearchRequest(query="Localized", locale=Locale.RU)
        )
        assert len(results) == 1
        assert results[0].locale is Locale.RU
        saved = await gateway.select_metadata(
            token=results[0].token,
            request=MetadataSelectionRequest(),
            locale=Locale.RU,
        )
        assert saved.item.provider_key == fake_provider.manifest.key
        assert saved.item.metadata.titles == {"ru": "Fixture"}
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
        provider=fake_provider.manifest.key,
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
                    MediaItem.provider_key == fake_provider.manifest.key
                )
            )
            == 0
        )

        saved = await gateway.select_metadata(
            token=confirmation,
            request=MetadataSelectionRequest(confirm_similarity=True),
            locale=Locale.EN,
        )
        assert saved.item.provider_key == fake_provider.manifest.key
        assert (
            database.scalar(
                select(func.count(MetadataRevision.id)).where(
                    MetadataRevision.media_item_id == saved.item.id
                )
            )
            == 1
        )

    asyncio.run(scenario())
