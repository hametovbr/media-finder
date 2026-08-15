"""Focused application and persistence contract for the catalog context."""

from __future__ import annotations

import ast
import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from media_finder_sdk import MediaKind, NormalizedMetadata, Provenance, ProviderPayload
from pydantic import ValidationError

ROOT = Path(__file__).parents[3]
CATALOG_ROOT = ROOT / "packages" / "core" / "src" / "media_finder_core" / "catalog"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _catalog_api(*, persistence: bool = False) -> SimpleNamespace:
    try:
        models = importlib.import_module("media_finder_core.catalog.models")
        commands = importlib.import_module("media_finder_core.catalog.commands")
        queries = importlib.import_module("media_finder_core.catalog.queries")
        ports = importlib.import_module("media_finder_core.catalog.ports")
        persistence_module = (
            importlib.import_module("media_finder_core.catalog.persistence")
            if persistence
            else None
        )
    except ModuleNotFoundError as error:
        pytest.fail(f"catalog bounded context is missing: {error.name}")

    required = {
        "CatalogIdentity": getattr(models, "CatalogIdentity", None),
        "CatalogPage": getattr(models, "CatalogPage", None),
        "CollectionSnapshot": getattr(models, "CollectionSnapshot", None),
        "ItemResolution": getattr(models, "ItemResolution", None),
        "MediaItemSnapshot": getattr(models, "MediaItemSnapshot", None),
        "MetadataRevisionSnapshot": getattr(models, "MetadataRevisionSnapshot", None),
        "RevisionDraft": getattr(models, "RevisionDraft", None),
        "CatalogCommands": getattr(commands, "CatalogCommands", None),
        "CatalogQueries": getattr(queries, "CatalogQueries", None),
        "CatalogRepository": getattr(ports, "CatalogRepository", None),
        "CatalogQueryPort": getattr(ports, "CatalogQueryPort", None),
    }
    missing = sorted(name for name, value in required.items() if value is None)
    assert missing == [], f"catalog public application types are missing: {missing}"
    return SimpleNamespace(
        **required,
        models=models,
        commands_module=commands,
        queries_module=queries,
        ports_module=ports,
        persistence=persistence_module,
    )


def _identity(api: SimpleNamespace, provider: str, external_id: str, kind: MediaKind):
    return api.CatalogIdentity(
        provider_id=provider,
        external_id=external_id,
        media_kind=kind,
    )


def _metadata(
    *,
    provider: str = "manual",
    external_id: str = "item-1",
    kind: MediaKind = MediaKind.MOVIE,
    title: str = "Spirited Away",
    year: int = 2001,
) -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=kind,
        titles={"en": title},
        year=year,
        provenance=Provenance(
            provider_id=provider,
            external_id=external_id,
            locale="en",
            fetched_at=NOW,
        ),
    )


def _draft(
    api: SimpleNamespace,
    *,
    provider: str = "manual",
    external_id: str = "item-1",
    kind: MediaKind = MediaKind.MOVIE,
    title: str = "Spirited Away",
    year: int = 2001,
):
    normalized = _metadata(
        provider=provider,
        external_id=external_id,
        kind=kind,
        title=title,
        year=year,
    )
    return api.RevisionDraft(
        raw_payload=ProviderPayload(data={"title": title, "year": year}),
        normalized=normalized,
        overrides={},
        effective=normalized,
        refresh_after=None,
        expires_at=None,
        created_at=NOW,
    )


def _updated(value: Any, **changes: object):
    if hasattr(value, "model_copy"):
        return value.model_copy(update=changes)
    return replace(value, **changes)


class _MemoryCatalog:
    """A deliberately simple port fake; application invariants remain in services."""

    def __init__(self, api: SimpleNamespace) -> None:
        self.api = api
        self.collections: dict[str, Any] = {}
        self.items: dict[str, Any] = {}
        self.revisions: dict[str, list[Any]] = {}
        self._collection_sequence = 0
        self._item_sequence = 0
        self._revision_sequence = 0

    def add_collection(self, name: str, created_at: datetime):
        self._collection_sequence += 1
        value = self.api.CollectionSnapshot(
            id=f"collection-{self._collection_sequence:03}",
            name=name,
            archived_at=None,
            created_at=created_at,
        )
        self.collections[value.id] = value
        return value

    def get_collection(self, collection_id: str):
        return self.collections.get(collection_id)

    def set_collection_archived(self, collection_id: str, archived_at: datetime | None):
        current = self.collections[collection_id]
        updated = _updated(current, archived_at=archived_at)
        self.collections[collection_id] = updated
        return updated

    def find_item_by_identity(self, identity: Any):
        return next(
            (
                item
                for item in self.items.values()
                if item.identity.provider_id == identity.provider_id
                and item.identity.external_id == identity.external_id
            ),
            None,
        )

    def add_item(self, identity: Any, created_at: datetime):
        self._item_sequence += 1
        value = self.api.MediaItemSnapshot(
            id=f"item-{self._item_sequence:03}",
            identity=identity,
            collection_id=None,
            normalized_title=None,
            year=None,
            current_revision_id=None,
            archived_at=None,
            created_at=created_at,
        )
        self.items[value.id] = value
        self.revisions[value.id] = []
        return value

    def get_item(self, item_id: str):
        return self.items.get(item_id)

    def append_revision(self, item_id: str, draft: Any):
        self._revision_sequence += 1
        item = self.items[item_id]
        item_revisions = self.revisions[item_id]
        revision = self.api.MetadataRevisionSnapshot(
            id=f"revision-{self._revision_sequence:03}",
            media_item_id=item_id,
            revision_number=len(item_revisions) + 1,
            identity=item.identity,
            locale=draft.normalized.provenance.locale,
            schema_version=draft.normalized.schema_version,
            raw_payload=draft.raw_payload,
            normalized=draft.normalized,
            overrides=draft.overrides,
            effective=draft.effective,
            refresh_after=draft.refresh_after,
            expires_at=draft.expires_at,
            created_at=draft.created_at,
        )
        item_revisions.append(revision)
        title = next(iter(draft.effective.titles.values())).casefold()
        self.items[item_id] = _updated(
            item,
            normalized_title=title,
            year=draft.effective.year,
            current_revision_id=revision.id,
        )
        return revision

    def set_item_archived(self, item_id: str, archived_at: datetime | None):
        updated = _updated(self.items[item_id], archived_at=archived_at)
        self.items[item_id] = updated
        return updated

    def set_item_collection(self, item_id: str, collection_id: str | None):
        updated = _updated(self.items[item_id], collection_id=collection_id)
        self.items[item_id] = updated
        return updated

    def list_revisions(self, item_id: str):
        return tuple(self.revisions.get(item_id, ()))

    def page_collections(
        self,
        *,
        archived: bool,
        limit: int,
        after: str | None,
    ):
        values = sorted(
            (
                value
                for value in self.collections.values()
                if (value.archived_at is not None) is archived
            ),
            key=lambda value: (value.name.casefold(), value.id),
        )
        return self._page(values, limit, after)

    def page_items(
        self,
        *,
        archived: bool,
        collection_id: str | None,
        uncategorized: bool,
        limit: int,
        after: str | None,
    ):
        values = sorted(
            (
                value
                for value in self.items.values()
                if (value.archived_at is not None) is archived
                and (collection_id is None or value.collection_id == collection_id)
                and (not uncategorized or value.collection_id is None)
            ),
            key=lambda value: (value.normalized_title or "", value.id),
        )
        return self._page(values, limit, after)

    def find_similar(
        self,
        *,
        normalized_title: str,
        year: int | None,
        excluding_provider_id: str,
    ):
        return tuple(
            value
            for value in self.items.values()
            if value.normalized_title == normalized_title.casefold()
            and value.year == year
            and value.identity.provider_id != excluding_provider_id
            and value.archived_at is None
        )

    def _page(self, values: list[Any], limit: int, after: str | None):
        offset = 0
        if after is not None:
            offset = next(index + 1 for index, value in enumerate(values) if value.id == after)
        selected = tuple(values[offset : offset + limit])
        next_after = selected[-1].id if selected and offset + len(selected) < len(values) else None
        return self.api.CatalogPage(items=selected, next_after=next_after)


def _services(api: SimpleNamespace):
    repository = _MemoryCatalog(api)
    commands = api.CatalogCommands(repository=repository, clock=lambda: NOW)
    queries = api.CatalogQueries(query_port=repository)
    return repository, commands, queries


def test_catalog_values_are_deeply_immutable_and_ports_are_framework_free() -> None:
    api = _catalog_api()
    repository, commands, _ = _services(api)
    result = commands.get_or_create_item(_identity(api, "manual", "item-1", MediaKind.MOVIE))
    draft = _draft(api)
    revision = commands.append_revision(result.item.id, draft)

    assert getattr(api.CatalogRepository, "_is_protocol", False) is True
    assert getattr(api.CatalogQueryPort, "_is_protocol", False) is True
    assert all(
        hasattr(repository, name)
        for name in (
            "add_collection",
            "find_item_by_identity",
            "append_revision",
            "page_collections",
            "page_items",
        )
    )
    with pytest.raises((FrozenInstanceError, AttributeError, ValidationError)):
        result.item.collection_id = "other"
    with pytest.raises((FrozenInstanceError, AttributeError, ValidationError)):
        revision.revision_number = 99
    with pytest.raises(TypeError):
        draft.overrides["plot"] = "mutated"
    nested_draft = replace(
        draft,
        overrides={"nested": {"value": "original"}, "rows": [{"value": "original"}]},
    )
    with pytest.raises(TypeError):
        nested_draft.overrides["nested"]["value"] = "mutated"
    with pytest.raises(TypeError):
        nested_draft.overrides["rows"][0]["value"] = "mutated"
    with pytest.raises(TypeError):
        revision.effective.titles["en"] = "mutated"

    forbidden: list[str] = []
    for name in ("models.py", "commands.py", "queries.py", "ports.py"):
        path = CATALOG_ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                modules = []
            forbidden.extend(
                f"{name}:{node.lineno}:{module}"
                for module in modules
                if module == "sqlalchemy"
                or module.startswith("sqlalchemy.")
                or module == "fastapi"
                or module.startswith("fastapi.")
            )
    assert forbidden == []


def test_collections_create_archive_and_restore_without_deletion() -> None:
    api = _catalog_api()
    repository, commands, queries = _services(api)

    created = commands.create_collection("Kids")
    archived = commands.archive_collection(created.id)
    restored = commands.restore_collection(created.id)

    assert created.name == "Kids"
    assert archived.id == created.id and archived.archived_at == NOW
    assert restored.id == created.id and restored.archived_at is None
    assert repository.get_collection(created.id) == restored
    assert tuple(queries.list_collections().items) == (restored,)


def test_exact_identity_returns_existing_and_rejects_a_kind_change() -> None:
    api = _catalog_api()
    repository, commands, _ = _services(api)
    movie = _identity(api, "tmdb", "129", MediaKind.MOVIE)

    first = commands.get_or_create_item(movie)
    duplicate = commands.get_or_create_item(movie)

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.item is first.item
    assert len(repository.items) == 1

    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        commands.get_or_create_item(_identity(api, "tmdb", "129", MediaKind.SERIES))
    assert len(repository.items) == 1


def test_revision_append_is_immutable_and_selects_only_the_new_current_revision() -> None:
    api = _catalog_api()
    repository, commands, queries = _services(api)
    item = commands.get_or_create_item(_identity(api, "manual", "item-1", MediaKind.MOVIE)).item

    first = commands.append_revision(item.id, _draft(api, title="Original", year=2001))
    first_dump = first
    second = commands.append_revision(item.id, _draft(api, title="Updated", year=2002))
    current_item = repository.get_item(item.id)

    assert first.revision_number == 1
    assert second.revision_number == 2
    assert queries.list_revisions(item.id) == (first, second)
    assert queries.list_revisions(item.id)[0] == first_dump
    assert current_item.current_revision_id == second.id
    assert current_item.normalized_title == "updated"
    assert current_item.year == 2002


def test_duplicate_resolution_does_not_append_until_explicit_revision_command() -> None:
    api = _catalog_api()
    _, commands, queries = _services(api)
    identity = _identity(api, "manual", "item-1", MediaKind.MOVIE)

    item = commands.get_or_create_item(identity).item
    duplicate = commands.get_or_create_item(identity)

    assert duplicate.created is False
    assert queries.list_revisions(item.id) == ()
    commands.append_revision(item.id, _draft(api))
    assert len(queries.list_revisions(item.id)) == 1
    commands.get_or_create_item(identity)
    assert len(queries.list_revisions(item.id)) == 1


def test_revision_identity_and_kind_mismatch_leave_prior_state_unchanged() -> None:
    api = _catalog_api()
    _, commands, queries = _services(api)
    item = commands.get_or_create_item(_identity(api, "manual", "item-1", MediaKind.MOVIE)).item
    first = commands.append_revision(item.id, _draft(api))

    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        commands.append_revision(
            item.id,
            _draft(api, provider="manual", external_id="other"),
        )
    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        commands.append_revision(
            item.id,
            _draft(api, provider="manual", external_id="item-1", kind=MediaKind.SERIES),
        )

    assert queries.list_revisions(item.id) == (first,)


def test_similarity_is_cross_provider_casefolded_and_excludes_archived_items() -> None:
    api = _catalog_api()
    _, commands, queries = _services(api)
    manual = commands.get_or_create_item(_identity(api, "manual", "manual-1", MediaKind.MOVIE)).item
    commands.append_revision(
        manual.id,
        _draft(api, external_id="manual-1", title="Spirited Away", year=2001),
    )
    tmdb = commands.get_or_create_item(_identity(api, "tmdb", "129", MediaKind.MOVIE)).item
    commands.append_revision(
        tmdb.id,
        _draft(api, provider="tmdb", external_id="129", title="Spirited Away", year=2001),
    )

    similar = queries.find_similar(
        title="SPIRITED AWAY",
        year=2001,
        excluding_provider_id="tmdb",
    )
    assert [value.id for value in similar] == [manual.id]

    commands.archive_item(manual.id)
    assert (
        queries.find_similar(
            title="Spirited Away",
            year=2001,
            excluding_provider_id="tmdb",
        )
        == ()
    )


def test_item_move_and_archive_preserve_identity_and_revisions() -> None:
    api = _catalog_api()
    _, commands, queries = _services(api)
    collection = commands.create_collection("Movies")
    identity = _identity(api, "manual", "item-1", MediaKind.MOVIE)
    item = commands.get_or_create_item(identity).item
    revision = commands.append_revision(item.id, _draft(api))

    moved = commands.move_item(item.id, collection.id)
    archived = commands.archive_item(item.id)

    assert moved.collection_id == collection.id
    assert archived.identity == identity
    assert archived.archived_at == NOW
    assert queries.list_revisions(item.id) == (revision,)
    assert queries.list_items(archived=False).items == ()
    assert queries.list_items(archived=True).items == (archived,)


def test_catalog_queries_are_stably_ordered_bounded_and_continuable() -> None:
    api = _catalog_api()
    _, commands, queries = _services(api)
    for number in range(105, 0, -1):
        commands.create_collection(f"Collection {number:03}")

    first = queries.list_collections()
    second = queries.list_collections(after=first.next_after)
    third = queries.list_collections(after=second.next_after)

    assert len(first.items) == 50 and first.next_after is not None
    assert len(second.items) == 50 and second.next_after is not None
    assert len(third.items) == 5 and third.next_after is None
    assert not ({value.id for value in first.items} & {value.id for value in second.items})
    names = [value.name for value in (*first.items, *second.items, *third.items)]
    assert names == sorted(names)

    with pytest.raises(ValueError, match="catalog_query_limit_invalid"):
        queries.list_collections(limit=101)
    with pytest.raises(ValueError, match="catalog_query_limit_invalid"):
        queries.list_items(limit=0)


def test_catalog_persistence_keeps_current_table_names_and_returns_only_snapshots() -> None:
    api = _catalog_api(persistence=True)
    persistence = api.persistence
    repository_type = getattr(persistence, "SqlAlchemyCatalogRepository", None)
    assert repository_type is not None
    table_names = {
        value.__tablename__
        for value in vars(persistence).values()
        if isinstance(value, type) and hasattr(value, "__tablename__")
    }
    assert table_names == {"collections", "media_items", "metadata_revisions"}


def test_sqlalchemy_repository_never_commits_and_database_rollback_is_atomic(database) -> None:
    api = _catalog_api(persistence=True)
    repository_type = getattr(api.persistence, "SqlAlchemyCatalogRepository", None)
    assert repository_type is not None
    repository = repository_type(database)
    commands = api.CatalogCommands(repository=repository, clock=lambda: NOW)
    queries = api.CatalogQueries(query_port=repository)

    collection = commands.create_collection("Rollback")
    item = commands.get_or_create_item(_identity(api, "manual", "rollback-1", MediaKind.MOVIE)).item
    commands.move_item(item.id, collection.id)
    commands.append_revision(item.id, _draft(api, external_id="rollback-1"))
    database.flush()
    assert queries.list_collections().items == (collection,)

    database.rollback()

    assert queries.list_collections().items == ()
    assert queries.list_items(archived=False).items == ()
    assert repository.find_item_by_identity(item.identity) is None


def test_sqlalchemy_repository_appends_without_mutating_a_committed_revision(database) -> None:
    api = _catalog_api(persistence=True)
    repository_type = getattr(api.persistence, "SqlAlchemyCatalogRepository", None)
    assert repository_type is not None
    repository = repository_type(database)
    commands = api.CatalogCommands(repository=repository, clock=lambda: NOW)
    queries = api.CatalogQueries(query_port=repository)
    item = commands.get_or_create_item(
        _identity(api, "manual", "persisted-1", MediaKind.MOVIE)
    ).item
    first = commands.append_revision(
        item.id,
        _draft(api, external_id="persisted-1", title="Original", year=2001),
    )
    database.commit()

    second = commands.append_revision(
        item.id,
        _draft(api, external_id="persisted-1", title="Updated", year=2002),
    )
    database.commit()
    revisions = queries.list_revisions(item.id)

    assert revisions[0] == first
    assert revisions[0].effective.titles == {"en": "Original"}
    assert revisions[1] == second
    assert repository.get_item(item.id).current_revision_id == second.id
    with pytest.raises((FrozenInstanceError, AttributeError, ValidationError)):
        revisions[0].locale = "ru"

    record = database.get(api.persistence.MediaItemRecord, item.id)
    record.kind = MediaKind.SERIES.value
    with pytest.raises(ValueError, match="identity is immutable"):
        database.commit()
    database.rollback()
    assert repository.get_item(item.id).identity.media_kind is MediaKind.MOVIE
    assert queries.list_revisions(item.id)[0].normalized.kind is MediaKind.MOVIE


def test_sqlalchemy_page_cursor_keeps_the_original_sort_key_when_title_changes(database) -> None:
    api = _catalog_api(persistence=True)
    repository = api.persistence.SqlAlchemyCatalogRepository(database)
    commands = api.CatalogCommands(repository=repository, clock=lambda: NOW)
    queries = api.CatalogQueries(query_port=repository)
    items = {}
    for number, title in enumerate(("Alpha", "Beta", "Gamma"), start=1):
        external_id = f"mutable-{number}"
        item = commands.get_or_create_item(
            _identity(api, "manual", external_id, MediaKind.MOVIE)
        ).item
        commands.append_revision(
            item.id,
            _draft(api, external_id=external_id, title=title),
        )
        items[title] = item

    first = queries.list_items(limit=2)
    assert [value.normalized_title for value in first.items] == ["alpha", "beta"]
    assert first.next_after is not None

    commands.append_revision(
        items["Beta"].id,
        _draft(api, external_id="mutable-2", title="Zeta"),
    )
    second = queries.list_items(limit=10, after=first.next_after)

    assert items["Gamma"].id in {value.id for value in second.items}


def test_sqlalchemy_collection_cursor_uses_one_unicode_sort_key(database) -> None:
    api = _catalog_api(persistence=True)
    repository = api.persistence.SqlAlchemyCatalogRepository(database)
    commands = api.CatalogCommands(repository=repository, clock=lambda: NOW)
    queries = api.CatalogQueries(query_port=repository)
    for name in ("Ömega", "Älpha", "Ångström"):
        commands.create_collection(name)

    first = queries.list_collections(limit=1)
    second = queries.list_collections(limit=1, after=first.next_after)
    third = queries.list_collections(limit=1, after=second.next_after)

    assert [page.items[0].name for page in (first, second, third)] == [
        "Älpha",
        "Ångström",
        "Ömega",
    ]
    assert third.next_after is None
