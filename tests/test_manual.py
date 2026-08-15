import csv
import io
from uuid import UUID, uuid4

import pytest

from media_finder.domain import CatalogService
from media_finder.manual import ManualCatalogService
from media_finder.modules.manual import ManualImportError, ManualProvider


def movie_document(external_id: str | None = None) -> dict:
    value = {
        "schema_version": "1",
        "kind": "movie",
        "locale": "en",
        "titles": {"en": "The Snow Queen"},
        "year": 1957,
        "plot": "A restored fairy tale.",
    }
    if external_id is not None:
        value["external_id"] = external_id
    return value


def test_complete_json_import_preserves_or_allocates_uuid4_atomically(database) -> None:
    provider = ManualCatalogService(CatalogService(database), ManualProvider())
    supplied = uuid4()
    item = provider.import_json(movie_document(str(supplied)))
    assert item.external_id == str(supplied)
    allocated = provider.import_json(movie_document())
    assert UUID(allocated.external_id).version == 4
    before = database.query(type(item)).count()
    with pytest.raises(ManualImportError):
        provider.import_json(movie_document("not-a-v4"))
    assert database.query(type(item)).count() == before


def test_existing_identity_requires_explicit_confirmation(database) -> None:
    provider = ManualCatalogService(CatalogService(database), ManualProvider())
    identity = str(uuid4())
    original = provider.import_json(movie_document(identity))
    result = provider.import_json(movie_document(identity))
    assert result.id == original.id
    assert len(result.revisions) == 1
    updated = provider.import_json(
        movie_document(identity) | {"plot": "Updated"}, confirm_existing=True
    )
    assert len(updated.revisions) == 2


def test_episode_csv_import_is_atomic_and_preserves_identity(database) -> None:
    provider = ManualCatalogService(CatalogService(database), ManualProvider())
    series = provider.import_json(
        {
            "schema_version": "1",
            "kind": "series",
            "locale": "en",
            "titles": {"en": "Local Animation"},
            "seasons": [],
        }
    )
    identity = series.external_id
    good = io.StringIO(
        "season,episode,title,plot,air_date\n0,1,Special,Bonus,2024-01-01\n1,1,Pilot,Start,2024-02-01\n"
    )
    provider.import_episode_csv(series.id, good.read())
    assert series.external_id == identity
    assert series.revisions[-1].effective_payload["seasons"][0]["number"] == 0
    count = len(series.revisions)
    bad = io.StringIO("season,episode,title\n1,2,Valid\ninvalid,3,Broken\n")
    with pytest.raises((ManualImportError, csv.Error)):
        provider.import_episode_csv(series.id, bad.read())
    assert len(series.revisions) == count
