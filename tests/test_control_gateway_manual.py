import asyncio
from uuid import uuid4

import pytest
from gateway_fixtures import create_gateway
from media_finder_control import ControlFailure, Locale
from media_finder_control.manual import (
    ArtworkDocument,
    EpisodeDocument,
    ManualDocumentV1,
    PersonDocument,
    SeasonDocument,
)
from media_finder_control.models import EpisodeImportRequest, ManualImportRequest
from media_finder_core.catalog.persistence import MetadataRevisionRecord as MetadataRevision
from media_finder_server.control_gateway import BackendControlGateway
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _gateway(database: Session) -> BackendControlGateway:
    return create_gateway(database)


def _rich_document(identity: str | None = None, title: str = "Manual Series") -> ManualDocumentV1:
    return ManualDocumentV1(
        external_id=identity,
        kind="series",
        locale="en",
        titles={"en": title, "ru": "Example"},
        plot="Plot",
        provider_ids={"local": "series"},
        people=(PersonDocument(name="Director", role="director"),),
        artwork=(ArtworkDocument(kind="poster", url="https://example.test/poster.jpg"),),
        seasons=(
            SeasonDocument(
                number=0,
                provider_ids={"local": "specials"},
                episodes=(
                    EpisodeDocument(
                        number=1,
                        title="Special",
                        provider_ids={"local": "special-1"},
                    ),
                ),
            ),
        ),
    )


def test_manual_create_and_existing_identity_confirmation_are_atomic(database: Session) -> None:
    gateway = _gateway(database)
    identity = str(uuid4())

    async def scenario() -> None:
        created = await gateway.import_manual(
            request=ManualImportRequest(document=_rich_document(identity))
        )
        assert created.item is not None
        assert created.item.external_id == identity
        assert created.item.metadata.seasons[0].episodes[0].provider_ids == {"local": "special-1"}

        uppercase = _rich_document(identity.upper(), title="Updated")
        pending = await gateway.import_manual(request=ManualImportRequest(document=uppercase))
        assert pending.item is None
        assert pending.confirmation_token is not None
        assert database.scalar(select(func.count(MetadataRevision.id))) == 1

        confirmed = await gateway.import_manual(
            request=ManualImportRequest(document=uppercase),
            confirmation_token=pending.confirmation_token,
        )
        assert confirmed.item is not None
        assert confirmed.item.metadata.titles["en"] == "Updated"
        assert database.scalar(select(func.count(MetadataRevision.id))) == 2

        with pytest.raises(ControlFailure) as consumed:
            await gateway.import_manual(
                request=ManualImportRequest(document=uppercase),
                confirmation_token=pending.confirmation_token,
            )
        assert consumed.value.status == 410

    asyncio.run(scenario())


def test_manual_edit_preserves_complete_document_and_requires_confirmation(
    database: Session,
) -> None:
    gateway = _gateway(database)

    async def scenario() -> None:
        created = await gateway.import_manual(
            request=ManualImportRequest(document=_rich_document())
        )
        assert created.item is not None
        edited = _rich_document(created.item.external_id, title="Edited")
        pending = await gateway.edit_manual(item_id=created.item.id, document=edited)
        assert pending.confirmation_token is not None
        confirmed = await gateway.edit_manual(
            item_id=created.item.id,
            document=edited,
            confirmation_token=pending.confirmation_token,
        )
        assert confirmed.item is not None
        assert confirmed.item.metadata.titles == {"en": "Edited", "ru": "Example"}
        assert confirmed.item.metadata.people[0].name == "Director"
        assert str(confirmed.item.metadata.artwork[0].url) == "https://example.test/poster.jpg"

    asyncio.run(scenario())


def test_manual_episode_csv_is_bounded_and_atomic(database: Session) -> None:
    gateway = _gateway(database)

    async def scenario() -> None:
        created = await gateway.import_manual(
            request=ManualImportRequest(document=_rich_document())
        )
        assert created.item is not None
        with pytest.raises(ControlFailure) as invalid:
            await gateway.import_episodes(
                item_id=created.item.id,
                request=EpisodeImportRequest(
                    csv="season,episode,title\n1,1,Valid\nnot-a-number,2,Broken\n"
                ),
                locale=Locale.EN,
            )
        assert invalid.value.error.code == "manual_import_invalid"
        assert database.scalar(select(func.count(MetadataRevision.id))) == 1

        updated = await gateway.import_episodes(
            item_id=created.item.id,
            request=EpisodeImportRequest(csv="season,episode,title\n1,1,Pilot\n"),
            locale=Locale.EN,
        )
        assert updated.metadata.seasons[-1].episodes[0].title == "Pilot"
        assert database.scalar(select(func.count(MetadataRevision.id))) == 2

    asyncio.run(scenario())
