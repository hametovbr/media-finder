import asyncio
import inspect

import pytest
from catalog_fixtures import CatalogFixture as CatalogService
from catalog_fixtures import RevisionInput
from gateway_fixtures import create_gateway
from media_finder_control import ControlFailure, ControlGateway, Locale, PageRequest
from media_finder_sdk import MediaKind, NormalizedMetadata, Provenance
from media_finder_server.control_gateway import BackendControlGateway
from sqlalchemy.orm import Session


def _gateway(database: Session) -> BackendControlGateway:
    return create_gateway(database)


def test_real_gateway_implements_every_public_async_operation(database: Session) -> None:
    gateway = _gateway(database)
    methods = {
        name
        for name, member in inspect.getmembers(ControlGateway)
        if inspect.iscoroutinefunction(member) and not name.startswith("_")
    }

    assert methods
    assert all(inspect.iscoroutinefunction(getattr(gateway, name, None)) for name in methods)


def test_collection_and_item_operations_share_stable_gateway_failures(database: Session) -> None:
    catalog = CatalogService(database)
    item, _ = catalog.get_or_create_item("manual", "item-1", MediaKind.MOVIE)
    catalog.add_revision(
        item,
        RevisionInput.from_normalized(
            NormalizedMetadata(
                kind=MediaKind.MOVIE,
                titles={"en": "Example"},
                provenance=Provenance(provider_id="manual", external_id="item-1", locale="en"),
            )
        ),
    )
    gateway = _gateway(database)

    async def scenario() -> None:
        collection = await gateway.create_collection(name="Movies")
        moved = await gateway.change_media_item(
            item_id=item.id,
            collection_id=collection.id,
            archived=None,
            locale=Locale.EN,
        )
        assert moved.collection_id == collection.id
        assert (await gateway.get_media_item(item_id=item.id, locale=Locale.EN)).id == item.id

        archived_item = await gateway.change_media_item(
            item_id=item.id,
            collection_id=collection.id,
            archived=True,
            locale=Locale.EN,
        )
        assert archived_item.archived is True
        archived_collection = await gateway.change_collection(
            collection_id=collection.id, archived=True
        )
        assert archived_collection.archived is True
        page = await gateway.list_collections(page=PageRequest(), archived=True)
        assert [value.id for value in page.items] == [collection.id]

        with pytest.raises(ControlFailure) as missing:
            await gateway.get_media_item(item_id="missing", locale=Locale.EN)
        assert missing.value.status == 404
        assert missing.value.error.code == "media_item_not_found"

    asyncio.run(scenario())
