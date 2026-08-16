import asyncio
from datetime import UTC, datetime

import pytest
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Collection
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder_control import ControlFailure, Locale, PageRequest
from media_finder_core.platform import EphemeralCache
from media_finder_server import create_legacy_module_registry
from media_finder_server.control_gateway import BackendControlGateway, CursorCodec
from sqlalchemy.orm import Session, sessionmaker

REGISTRY = create_legacy_module_registry()


def _sessions(database: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=database.get_bind(), expire_on_commit=False)


def test_cursor_is_signed_and_bound_to_resource_filters_and_position() -> None:
    codec = CursorCodec(secret=b"cursor-secret-for-tests")
    token = codec.encode(
        resource="media-items",
        filters={"archived": False, "collection": None},
        position=("example", "item-1"),
    )

    assert codec.decode(
        token,
        resource="media-items",
        filters={"archived": False, "collection": None},
    ) == ("example", "item-1")
    with pytest.raises(ControlFailure, match="cursor_invalid"):
        codec.decode(
            token,
            resource="collections",
            filters={"archived": False, "collection": None},
        )
    with pytest.raises(ControlFailure, match="cursor_invalid"):
        codec.decode(
            f"{token[:-1]}x",
            resource="media-items",
            filters={"archived": False, "collection": None},
        )


def test_gateway_pages_collections_with_default_limit_and_no_repeats(database: Session) -> None:
    database.add_all(Collection(name=f"Collection {number:03}") for number in range(105))
    database.commit()
    gateway = BackendControlGateway(
        sessions=_sessions(database),
        cursor_secret=b"cursor-secret-for-tests",
        metadata_selections=EphemeralCache(),
        manual_drafts=EphemeralCache(),
        registry=REGISTRY,
    )

    async def scenario() -> None:
        first = await gateway.list_collections(page=PageRequest(), archived=False)
        assert len(first.items) == 50
        assert first.next_cursor is not None
        second = await gateway.list_collections(
            page=PageRequest(cursor=first.next_cursor), archived=False
        )
        assert len(second.items) == 50
        assert not ({item.id for item in first.items} & {item.id for item in second.items})

        with pytest.raises(ControlFailure) as mismatch:
            await gateway.list_collections(
                page=PageRequest(cursor=first.next_cursor), archived=True
            )
        assert mismatch.value.status == 422
        assert mismatch.value.error.code == "cursor_invalid"

    asyncio.run(scenario())


def test_gateway_pages_catalog_in_stable_order(database: Session) -> None:
    catalog = CatalogService(database)
    for number, title in enumerate(("Gamma", "Alpha", "Beta"), 1):
        item, _ = catalog.get_or_create_item("fixture", str(number), MediaKind.MOVIE)
        catalog.add_revision(
            item,
            RevisionInput.from_normalized(
                NormalizedMetadata(
                    kind=MediaKind.MOVIE,
                    titles={"en": title},
                    provenance=Provenance(
                        provider_key="fixture",
                        external_id=str(number),
                        locale="en",
                        fetched_at=datetime(2025, 1, 1, tzinfo=UTC),
                    ),
                )
            ),
        )
    gateway = BackendControlGateway(
        sessions=_sessions(database),
        cursor_secret=b"cursor-secret-for-tests",
        metadata_selections=EphemeralCache(),
        manual_drafts=EphemeralCache(),
        registry=REGISTRY,
    )

    async def scenario() -> None:
        first = await gateway.list_media_items(
            locale=Locale.EN,
            page=PageRequest(limit=2),
            collection_id=None,
            uncategorized=False,
            archived=False,
        )
        second = await gateway.list_media_items(
            locale=Locale.EN,
            page=PageRequest(limit=2, cursor=first.next_cursor),
            collection_id=None,
            uncategorized=False,
            archived=False,
        )
        assert [item.title for item in first.items] == ["Alpha", "Beta"]
        assert [item.title for item in second.items] == ["Gamma"]

    asyncio.run(scenario())
