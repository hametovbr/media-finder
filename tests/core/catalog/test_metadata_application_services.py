"""Decision-complete orchestration contract for the catalog metadata slice."""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from media_finder_sdk import (
    EpisodeTableDocument,
    MediaKind,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleError,
    ModuleFailureCategory,
    NormalizedMetadata,
    Provenance,
    ProviderPayload,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).parents[3]
CATALOG_ROOT = ROOT / "packages" / "core" / "src" / "media_finder_core" / "catalog"


def _api() -> SimpleNamespace:
    modules = {
        name: importlib.import_module(f"media_finder_core.catalog.{name}")
        for name in ("models", "metadata", "manual", "retention")
    }
    required = {
        "CatalogIdentity": getattr(modules["models"], "CatalogIdentity", None),
        "MediaItemSnapshot": getattr(modules["models"], "MediaItemSnapshot", None),
        "MetadataRevisionSnapshot": getattr(modules["models"], "MetadataRevisionSnapshot", None),
        "MetadataCatalogService": getattr(modules["metadata"], "MetadataCatalogService", None),
        "ManualCatalogService": getattr(modules["manual"], "ManualCatalogService", None),
        "MetadataRetentionService": getattr(modules["retention"], "MetadataRetentionService", None),
    }
    missing = sorted(name for name, value in required.items() if value is None)
    assert missing == [], f"catalog metadata application services are missing: {missing}"
    return SimpleNamespace(**required, **modules)


def _identity(
    provider_id: str = "provider-a",
    external_id: str = "item-1",
    kind: MediaKind = MediaKind.MOVIE,
    locale: str = "en",
) -> MetadataIdentity:
    return MetadataIdentity(
        provider_id=provider_id,
        external_id=external_id,
        media_kind=kind,
        locale=locale,
    )


def _metadata(
    identity: MetadataIdentity | None = None,
    *,
    title: str = "Spirited Away",
    year: int = 2001,
) -> NormalizedMetadata:
    selected = identity or _identity()
    return NormalizedMetadata(
        kind=selected.media_kind,
        titles={selected.locale: title},
        year=year,
        provenance=Provenance(
            provider_id=selected.provider_id,
            external_id=selected.external_id,
            locale=selected.locale,
            fetched_at=NOW,
        ),
    )


def _edit_result(
    identity: MetadataIdentity | None = None,
    *,
    title: str = "Spirited Away",
    year: int = 2001,
) -> MetadataEditResult:
    selected = identity or _identity()
    return MetadataEditResult(
        identity=selected,
        raw_payload=ProviderPayload(data={"title": title, "year": year}),
        metadata=_metadata(selected, title=title, year=year),
    )


class _MemoryCatalog:
    def __init__(self, api: SimpleNamespace) -> None:
        self.api = api
        self.items: dict[str, Any] = {}
        self.revisions: dict[str, list[Any]] = {}
        self._item_sequence = 0
        self._revision_sequence = 0
        self.fail_append = False
        self.fail_purge_ids: set[str] = set()

    def snapshot(self) -> tuple[dict[str, Any], dict[str, list[Any]], int, int]:
        return (
            dict(self.items),
            {key: list(value) for key, value in self.revisions.items()},
            self._item_sequence,
            self._revision_sequence,
        )

    def restore(self, state: tuple[dict[str, Any], dict[str, list[Any]], int, int]) -> None:
        self.items, self.revisions, self._item_sequence, self._revision_sequence = state

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

    def get_item(self, item_id: str):
        return self.items.get(item_id)

    def add_item(self, identity: Any, created_at: datetime):
        self._item_sequence += 1
        item = self.api.MediaItemSnapshot(
            id=f"item-{self._item_sequence:03}",
            identity=identity,
            collection_id=None,
            normalized_title=None,
            year=None,
            current_revision_id=None,
            archived_at=None,
            created_at=created_at,
        )
        self.items[item.id] = item
        self.revisions[item.id] = []
        return item

    def append_revision(self, item_id: str, draft: Any):
        if self.fail_append:
            raise RuntimeError("simulated append failure")
        self._revision_sequence += 1
        item = self.items[item_id]
        revision = self.api.MetadataRevisionSnapshot(
            id=f"revision-{self._revision_sequence:03}",
            media_item_id=item.id,
            revision_number=len(self.revisions[item.id]) + 1,
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
        self.revisions[item.id].append(revision)
        title = next(iter(draft.effective.titles.values())).casefold()
        self.items[item.id] = replace(
            item,
            normalized_title=title,
            year=draft.effective.year,
            current_revision_id=revision.id,
        )
        return revision

    def list_revisions(self, item_id: str):
        return tuple(self.revisions.get(item_id, ()))

    def get_revision(self, revision_id: str):
        return next(
            (
                revision
                for values in self.revisions.values()
                for revision in values
                if revision.id == revision_id
            ),
            None,
        )

    def find_similar(
        self,
        *,
        normalized_title: str,
        year: int | None,
        excluding_provider_id: str,
    ):
        return tuple(
            item
            for item in self.items.values()
            if item.normalized_title == normalized_title.casefold()
            and item.year == year
            and item.identity.provider_id != excluding_provider_id
            and item.archived_at is None
        )

    def retention_candidates(self, now: datetime):
        del now
        return tuple(
            revision
            for item in self.items.values()
            if item.current_revision_id is not None
            for revision in self.revisions[item.id]
            if revision.id == item.current_revision_id
        )

    def purge_revision(self, revision_id: str, attempted_at: datetime) -> None:
        if revision_id in self.fail_purge_ids:
            raise RuntimeError("simulated purge failure")
        self._replace_revision(
            revision_id,
            raw_payload=None,
            normalized=None,
            effective=None,
            expired_at=attempted_at,
            maintenance_status="purged",
            maintenance_error_code=None,
            maintenance_attempted_at=attempted_at,
        )

    def record_retention_failure(self, revision_id: str, code: str, attempted_at: datetime) -> None:
        self._replace_revision(
            revision_id,
            maintenance_status="failed",
            maintenance_error_code=code,
            maintenance_attempted_at=attempted_at,
        )

    def _replace_revision(self, revision_id: str, **changes: object) -> None:
        for _item_id, values in self.revisions.items():
            for index, revision in enumerate(values):
                if revision.id == revision_id:
                    values[index] = replace(revision, **changes)
                    return
        raise KeyError(revision_id)


class _UnitOfWork:
    def __init__(self, store: _MemoryCatalog) -> None:
        self.store = store
        self.write_active = False
        self.write_count = 0
        self.savepoint_count = 0
        self.rollback_count = 0
        self.on_next_write: Callable[[], None] | None = None

    @contextmanager
    def write(self) -> Iterator[_MemoryCatalog]:
        if self.on_next_write is not None:
            callback, self.on_next_write = self.on_next_write, None
            callback()
        before = self.store.snapshot()
        self.write_active = True
        self.write_count += 1
        try:
            yield self.store
        except BaseException:
            self.store.restore(before)
            self.rollback_count += 1
            raise
        finally:
            self.write_active = False

    @contextmanager
    def savepoint(self) -> Iterator[_MemoryCatalog]:
        before = self.store.snapshot()
        self.savepoint_count += 1
        try:
            yield self.store
        except BaseException:
            self.store.restore(before)
            self.rollback_count += 1
            raise


class _Provider:
    def __init__(
        self,
        uow: _UnitOfWork,
        identity: MetadataIdentity,
        *,
        title: str = "Spirited Away",
        description: str | None = None,
        poster_url: str | None = None,
        search_output: object | None = None,
        normalize_output: object | None = None,
        fetch_error: BaseException | None = None,
    ) -> None:
        self.uow = uow
        self.identity = identity
        self.title = title
        self.description = description
        self.poster_url = poster_url
        self.search_output = search_output
        self.last_search_result: MetadataSearchResult | None = None
        self.fetch_identity: MetadataIdentity | None = None
        self.normalize_output = normalize_output
        self.fetch_error = fetch_error
        self.search_calls = 0
        self.fetch_calls = 0
        self.normalize_calls = 0

    def validate(self) -> None: ...

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        assert self.uow.write_active is False
        self.search_calls += 1
        if self.search_output is not None:
            return (self.search_output,)  # type: ignore[return-value]
        self.last_search_result = MetadataSearchResult(
            provider_id=self.identity.provider_id,
            external_id=self.identity.external_id,
            media_kind=self.identity.media_kind,
            title=self.title,
            year=2001,
            locale=query.locale,
            description=self.description,
            poster_url=self.poster_url,
        )
        return (self.last_search_result,)

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        assert self.uow.write_active is False
        self.fetch_calls += 1
        self.fetch_identity = identity
        if self.fetch_error is not None:
            raise self.fetch_error
        return ProviderPayload(data={"identity": identity.external_id, "title": self.title})

    def normalize(self, payload: ProviderPayload, identity: MetadataIdentity) -> NormalizedMetadata:
        assert self.uow.write_active is False
        assert payload.data["identity"] == identity.external_id
        self.normalize_calls += 1
        if self.normalize_output is not None:
            return self.normalize_output  # type: ignore[return-value]
        return _metadata(identity, title=self.title)

    def close(self) -> None: ...


class _Editor:
    def __init__(
        self,
        uow: _UnitOfWork,
        import_result: MetadataEditResult,
        merge_result: MetadataEditResult | None = None,
    ) -> None:
        self.uow = uow
        self.import_result = import_result
        self.merge_result = merge_result or import_result
        self.import_calls = 0
        self.merge_calls = 0
        self.merge_current: NormalizedMetadata | None = None

    def import_document(self, document: MetadataImportDocument) -> MetadataEditResult:
        assert self.uow.write_active is False
        assert document.content()
        self.import_calls += 1
        return self.import_result

    def merge_episode_table(
        self, current: NormalizedMetadata, document: EpisodeTableDocument
    ) -> MetadataEditResult:
        assert self.uow.write_active is False
        assert document.content()
        self.merge_calls += 1
        self.merge_current = current
        return self.merge_result

    def close(self) -> None: ...


class _RetentionPolicy:
    def __init__(
        self,
        action: RetentionActionKind = RetentionActionKind.NONE,
        *,
        fail_with: BaseException | None = None,
    ) -> None:
        self.action = action
        self.fail_with = fail_with
        self.plan_calls = 0

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        return RetentionPolicy(refresh_after=created_at, expires_at=created_at)

    def plan(self, subject: Any, now: datetime) -> RetentionAction:
        del subject, now
        self.plan_calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return RetentionAction(
            kind=self.action, mandatory=self.action is not RetentionActionKind.NONE
        )

    def export_warning(self, policy: RetentionPolicy, now: datetime):
        del policy, now
        return None

    def close(self) -> None: ...


def _service_fixture() -> tuple[SimpleNamespace, _MemoryCatalog, _UnitOfWork]:
    api = _api()
    store = _MemoryCatalog(api)
    return api, store, _UnitOfWork(store)


def _seed_revision(
    api: SimpleNamespace,
    store: _MemoryCatalog,
    identity: MetadataIdentity,
    *,
    title: str = "Spirited Away",
) -> tuple[Any, Any]:
    catalog_identity = api.CatalogIdentity(
        provider_id=identity.provider_id,
        external_id=identity.external_id,
        media_kind=identity.media_kind,
    )
    item = store.add_item(catalog_identity, NOW)
    metadata = _metadata(identity, title=title)
    draft_type = api.models.RevisionDraft
    revision = store.append_revision(
        item.id,
        draft_type(
            raw_payload=ProviderPayload(data={"title": title}),
            normalized=metadata,
            overrides={},
            effective=metadata,
            refresh_after=NOW,
            expires_at=NOW,
            created_at=NOW,
        ),
    )
    return store.get_item(item.id), revision


def test_metadata_search_calls_only_selected_providers_and_revalidates_results() -> None:
    api, store, uow = _service_fixture()
    first = _Provider(uow, _identity("provider-a", "a-1"))
    second = _Provider(
        uow,
        _identity("provider-b", "b-1"),
        title="Second",
        description="A complete transient preview.",
        poster_url="https://images.example.test/posters/b-1.jpg",
    )
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)
    query = MetadataSearchQuery(query="spirited", locale="en")

    results = service.search(
        query=query,
        providers={"provider-a": first, "provider-b": second},
        selected_provider_ids=("provider-b",),
    )

    assert tuple(result.provider_id for result in results) == ("provider-b",)
    assert first.search_calls == 0
    assert second.search_calls == 1
    assert results[0] is not second.last_search_result
    assert results[0].description == "A complete transient preview."
    assert str(results[0].poster_url) == "https://images.example.test/posters/b-1.jpg"

    second.identity = _identity("provider-a", "wrong")
    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        service.search(
            query=query,
            providers={"provider-b": second},
            selected_provider_ids=("provider-b",),
        )

    class InvalidSearchResult:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {
                "provider_id": "provider-b",
                "external_id": "b-2",
                "media_kind": "movie",
                "title": "Invalid preview",
                "locale": "en",
                "description": None,
                "poster_url": "not a complete URL",
            }

    invalid = _Provider(
        uow,
        _identity("provider-b", "b-2"),
        search_output=InvalidSearchResult(),
    )
    with pytest.raises(ValueError, match="provider_output_invalid"):
        service.search(
            query=query,
            providers={"provider-b": invalid},
            selected_provider_ids=("provider-b",),
        )


def test_metadata_selection_uses_only_search_identity_not_transient_preview() -> None:
    api, store, uow = _service_fixture()
    provider = _Provider(
        uow,
        _identity(),
        description="Search-only description",
        poster_url="https://images.example.test/posters/item-1.jpg",
    )
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)
    result = service.search(
        query=MetadataSearchQuery(query="spirited", locale="en"),
        providers={"provider-a": provider},
        selected_provider_ids=("provider-a",),
    )[0]
    identity = MetadataIdentity(
        provider_id=result.provider_id,
        external_id=result.external_id,
        media_kind=result.media_kind,
        locale=result.locale,
    )

    selected = service.select(
        identity=identity,
        provider=provider,
        retention_policy=_RetentionPolicy(),
    )

    assert provider.fetch_identity == identity
    revision = store.get_revision(selected.item.current_revision_id)
    assert revision is not None
    serialized = revision.effective.model_dump(mode="json")
    assert "description" not in serialized
    assert "poster_url" not in serialized


def test_metadata_exact_duplicate_returns_existing_without_provider_io() -> None:
    api, store, uow = _service_fixture()
    identity = _identity()
    existing, revision = _seed_revision(api, store, identity)
    provider = _Provider(uow, identity)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    result = service.select(
        identity=identity,
        provider=provider,
        retention_policy=_RetentionPolicy(),
    )

    assert result.created is False
    assert result.item.id == existing.id
    assert store.list_revisions(existing.id) == (revision,)
    assert (provider.fetch_calls, provider.normalize_calls, uow.write_count) == (0, 0, 0)


def test_metadata_exact_duplicate_does_not_resolve_live_capabilities() -> None:
    api, store, uow = _service_fixture()
    identity = _identity()
    existing, _revision = _seed_revision(api, store, identity)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    def unexpected_resolution():
        raise AssertionError("exact duplicate must not resolve a live capability")

    result = service.select(
        identity=identity,
        provider=unexpected_resolution,
        retention_policy=unexpected_resolution,
    )

    assert result.created is False
    assert result.item.id == existing.id


def test_metadata_exact_duplicate_rejects_a_different_media_kind_without_provider_io() -> None:
    api, store, uow = _service_fixture()
    existing_identity = _identity(kind=MediaKind.MOVIE)
    _seed_revision(api, store, existing_identity)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    def unexpected_resolution():
        raise AssertionError("identity mismatch must not resolve a live capability")

    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        service.select(
            identity=_identity(kind=MediaKind.SERIES),
            provider=unexpected_resolution,
            retention_policy=unexpected_resolution,
        )

    assert uow.write_count == 0


def test_metadata_similarity_requires_confirmation_before_atomic_persistence() -> None:
    api, store, uow = _service_fixture()
    _seed_revision(api, store, _identity("provider-other", "other-1"))
    identity = _identity("provider-a", "new-1")
    provider = _Provider(uow, identity)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    with pytest.raises(ValueError, match="similarity_confirmation_required"):
        service.select(
            identity=identity,
            provider=provider,
            retention_policy=_RetentionPolicy(),
        )
    assert store.find_item_by_identity(identity) is None

    result = service.select(
        identity=identity,
        provider=provider,
        retention_policy=_RetentionPolicy(),
        confirm_similarity=True,
    )
    assert result.created is True
    assert len(store.list_revisions(result.item.id)) == 1


def test_metadata_similarity_is_rechecked_inside_write() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("provider-a", "new-race")
    provider = _Provider(uow, identity)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    def concurrent_similar_item() -> None:
        _seed_revision(api, store, _identity("provider-other", "similar-race"))

    uow.on_next_write = concurrent_similar_item
    with pytest.raises(ValueError, match="similarity_confirmation_required"):
        service.select(
            identity=identity,
            provider=provider,
            retention_policy=_RetentionPolicy(),
        )

    assert store.find_item_by_identity(identity) is None


def test_metadata_fetch_and_normalize_are_outside_write_and_identity_is_rechecked() -> None:
    api, store, uow = _service_fixture()
    identity = _identity()
    provider = _Provider(uow, identity)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    def concurrent_insert() -> None:
        _seed_revision(api, store, identity, title="Concurrent")

    uow.on_next_write = concurrent_insert
    result = service.select(
        identity=identity,
        provider=provider,
        retention_policy=_RetentionPolicy(),
    )

    assert result.created is False
    assert result.item.normalized_title == "concurrent"
    assert provider.fetch_calls == provider.normalize_calls == 1
    assert len(store.items) == 1


@pytest.mark.parametrize(
    ("output", "code"),
    [
        (object(), "provider_output_invalid"),
        (_metadata(_identity("provider-a", "wrong")), "provider_identity_mismatch"),
    ],
)
def test_metadata_revalidates_sdk_output_before_any_write(output: object, code: str) -> None:
    api, store, uow = _service_fixture()
    identity = _identity()
    provider = _Provider(uow, identity, normalize_output=output)
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    with pytest.raises(ValueError, match=code):
        service.select(
            identity=identity,
            provider=provider,
            retention_policy=_RetentionPolicy(),
        )

    assert store.items == {}
    assert uow.write_count == 0


def test_metadata_rejects_invalid_provider_payload_before_any_write() -> None:
    api, store, uow = _service_fixture()
    identity = _identity()
    provider = _Provider(uow, identity)
    provider.fetch = lambda ignored_identity: object()  # type: ignore[method-assign]
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    with pytest.raises(ValueError, match="provider_output_invalid"):
        service.select(
            identity=identity,
            provider=provider,
            retention_policy=_RetentionPolicy(),
        )

    assert store.items == {}
    assert uow.write_count == 0


def test_metadata_rejects_invalid_retention_output_before_any_write() -> None:
    api, store, uow = _service_fixture()
    identity = _identity()
    retention = _RetentionPolicy()
    retention.retention_for = lambda ignored_now: object()  # type: ignore[method-assign]
    service = api.MetadataCatalogService(query_port=store, unit_of_work=uow, clock=lambda: NOW)

    with pytest.raises(ValueError, match="provider_output_invalid"):
        service.select(
            identity=identity,
            provider=_Provider(uow, identity),
            retention_policy=retention,
        )

    assert store.items == {}
    assert uow.write_count == 0


def test_manual_import_uses_injected_editor_and_requires_duplicate_confirmation() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("local-provider", "local-1")
    existing, first_revision = _seed_revision(api, store, identity)
    editor = _Editor(uow, _edit_result(identity, title="Updated"))
    service = api.ManualCatalogService(
        query_port=store,
        unit_of_work=uow,
        editor=editor,
        provider_id=identity.provider_id,
        retention_policy=_RetentionPolicy(),
        clock=lambda: NOW,
    )
    document = MetadataImportDocument.from_bytes(b'{"title":"Updated"}')

    with pytest.raises(ValueError, match="duplicate_confirmation_required"):
        service.import_item(document=document)
    assert store.list_revisions(existing.id) == (first_revision,)

    result = service.import_item(document=document, confirm_duplicate=True)
    assert result.item.id == existing.id
    assert len(store.list_revisions(existing.id)) == 2
    assert editor.import_calls == 2


def test_manual_import_rechecks_duplicate_confirmation_inside_write() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("local-provider", "local-race")
    editor = _Editor(uow, _edit_result(identity, title="Candidate"))
    service = api.ManualCatalogService(
        query_port=store,
        unit_of_work=uow,
        editor=editor,
        provider_id=identity.provider_id,
        retention_policy=_RetentionPolicy(),
        clock=lambda: NOW,
    )

    def concurrent_insert() -> None:
        _seed_revision(api, store, identity, title="Concurrent")

    uow.on_next_write = concurrent_insert
    with pytest.raises(ValueError, match="duplicate_confirmation_required"):
        service.import_item(document=MetadataImportDocument.from_bytes(b'{"title":"Candidate"}'))

    existing = store.find_item_by_identity(identity)
    assert existing is not None
    assert len(store.list_revisions(existing.id)) == 1


def test_manual_orchestrator_has_no_concrete_provider_identifier_branch() -> None:
    path = CATALOG_ROOT / "manual.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    concrete_literals = {
        node.value.casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.casefold() in {"manual", "tmdb", "prowlarr", "qbittorrent"}
    }
    assert concrete_literals == set()


def test_manual_edit_rejects_changed_identity_before_persistence() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("local-provider", "local-1")
    item, revision = _seed_revision(api, store, identity)
    editor = _Editor(uow, _edit_result(_identity("local-provider", "other")))
    service = api.ManualCatalogService(
        query_port=store,
        unit_of_work=uow,
        editor=editor,
        provider_id=identity.provider_id,
        retention_policy=_RetentionPolicy(),
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        service.edit_item(
            item_id=item.id,
            document=MetadataImportDocument.from_bytes(b'{"title":"Changed"}'),
            expected_current_revision_id=revision.id,
        )

    assert store.list_revisions(item.id) == (revision,)
    assert uow.write_count == 0


def test_manual_episode_table_merges_the_current_snapshot_outside_write() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("local-provider", "series-1", MediaKind.SERIES)
    item, revision = _seed_revision(api, store, identity, title="Series")
    editor = _Editor(uow, _edit_result(identity, title="Series with episodes"))
    service = api.ManualCatalogService(
        query_port=store,
        unit_of_work=uow,
        editor=editor,
        provider_id=identity.provider_id,
        retention_policy=_RetentionPolicy(),
        clock=lambda: NOW,
    )

    service.import_episode_table(
        item_id=item.id,
        document=EpisodeTableDocument.from_bytes(b"season,episode,title\n0,1,Special"),
        expected_current_revision_id=revision.id,
    )

    assert editor.merge_calls == 1
    assert editor.merge_current is revision.effective
    assert len(store.list_revisions(item.id)) == 2


def test_manual_expected_current_prevents_lost_update_and_write_rolls_back_atomically() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("local-provider", "local-1")
    item, revision = _seed_revision(api, store, identity)
    editor = _Editor(uow, _edit_result(identity, title="Edited"))
    service = api.ManualCatalogService(
        query_port=store,
        unit_of_work=uow,
        editor=editor,
        provider_id=identity.provider_id,
        retention_policy=_RetentionPolicy(),
        clock=lambda: NOW,
    )

    def concurrent_revision() -> None:
        _seed_revision_on_item(api, store, item.id, identity, title="Concurrent")

    uow.on_next_write = concurrent_revision
    with pytest.raises(ValueError, match="catalog_current_revision_changed"):
        service.edit_item(
            item_id=item.id,
            document=MetadataImportDocument.from_bytes(b'{"title":"Edited"}'),
            expected_current_revision_id=revision.id,
        )
    assert [value.effective.titles["en"] for value in store.list_revisions(item.id)] == [
        "Spirited Away",
        "Concurrent",
    ]

    before = store.snapshot()
    store.fail_append = True
    with pytest.raises(RuntimeError, match="append failure"):
        service.edit_item(
            item_id=item.id,
            document=MetadataImportDocument.from_bytes(b'{"title":"Edited"}'),
            expected_current_revision_id=store.get_item(item.id).current_revision_id,
        )
    store.fail_append = False
    assert store.snapshot() == before
    assert uow.rollback_count >= 2


def _seed_revision_on_item(
    api: SimpleNamespace,
    store: _MemoryCatalog,
    item_id: str,
    identity: MetadataIdentity,
    *,
    title: str,
) -> Any:
    metadata = _metadata(identity, title=title)
    return store.append_revision(
        item_id,
        api.models.RevisionDraft(
            raw_payload=ProviderPayload(data={"title": title}),
            normalized=metadata,
            overrides={},
            effective=metadata,
            refresh_after=NOW,
            expires_at=NOW,
            created_at=NOW,
        ),
    )


def test_retention_purge_uses_configuration_free_policy_without_live_provider() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("provider-retained", "purge-1")
    item, revision = _seed_revision(api, store, identity)
    service = api.MetadataRetentionService(
        query_port=store,
        unit_of_work=uow,
        policies={identity.provider_id: _RetentionPolicy(RetentionActionKind.PURGE)},
        providers={},
        clock=lambda: NOW,
    )

    service.run()

    purged = store.get_revision(revision.id)
    assert purged.raw_payload is None
    assert purged.normalized is None
    assert purged.effective is None
    assert purged.maintenance_status == "purged"
    assert store.get_item(item.id).current_revision_id == revision.id


def test_retention_refresh_does_provider_io_outside_write_and_appends_revision() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("provider-refresh", "refresh-1")
    item, original = _seed_revision(api, store, identity, title="Original")
    provider = _Provider(uow, identity, title="Refreshed")
    service = api.MetadataRetentionService(
        query_port=store,
        unit_of_work=uow,
        policies={identity.provider_id: _RetentionPolicy(RetentionActionKind.REFRESH)},
        providers={identity.provider_id: provider},
        clock=lambda: NOW,
    )

    service.run()

    revisions = store.list_revisions(item.id)
    assert len(revisions) == 2
    assert revisions[0] == original
    assert revisions[0].effective.titles["en"] == "Original"
    assert revisions[1].effective.titles["en"] == "Refreshed"
    assert provider.fetch_calls == provider.normalize_calls == 1


@pytest.mark.parametrize("mode", ["missing", "safe-provider-error"])
def test_retention_records_only_stable_safe_failures(
    mode: str,
) -> None:
    api, store, uow = _service_fixture()
    identity = _identity("provider-failure", "failure-1")
    _, revision = _seed_revision(api, store, identity)
    expected_code = "metadata_provider_unavailable"
    providers: Mapping[str, _Provider] = {}
    if mode == "safe-provider-error":
        expected_code = "provider_timeout"
        providers = {
            identity.provider_id: _Provider(
                uow,
                identity,
                fetch_error=ModuleError(
                    category=ModuleFailureCategory.TIMEOUT,
                    code=expected_code,
                    safe_details={"operation": "retention"},
                ),
            )
        }
    service = api.MetadataRetentionService(
        query_port=store,
        unit_of_work=uow,
        policies={identity.provider_id: _RetentionPolicy(RetentionActionKind.REFRESH)},
        providers=providers,
        clock=lambda: NOW,
    )

    service.run()

    failed = store.get_revision(revision.id)
    assert failed.maintenance_status == "failed"
    assert failed.maintenance_error_code == expected_code
    assert "secret" not in repr(failed).casefold()


def test_retention_rejects_malformed_module_action_as_safe_failure() -> None:
    api, store, uow = _service_fixture()
    identity = _identity("provider-invalid-retention", "failure-1")
    _, revision = _seed_revision(api, store, identity)
    policy = _RetentionPolicy()
    policy.plan = lambda ignored_subject, ignored_now: object()  # type: ignore[method-assign]
    service = api.MetadataRetentionService(
        query_port=store,
        unit_of_work=uow,
        policies={identity.provider_id: policy},
        providers={},
        clock=lambda: NOW,
    )

    service.run()

    failed = store.get_revision(revision.id)
    assert failed.maintenance_status == "failed"
    assert failed.maintenance_error_code == "metadata_provider_maintenance_failed"


def test_retention_savepoint_failure_does_not_block_later_subject() -> None:
    api, store, uow = _service_fixture()
    first_identity = _identity("provider-retained", "first")
    second_identity = _identity("provider-retained", "second")
    _, first = _seed_revision(api, store, first_identity)
    _, second = _seed_revision(api, store, second_identity)
    store.fail_purge_ids.add(first.id)
    service = api.MetadataRetentionService(
        query_port=store,
        unit_of_work=uow,
        policies={first_identity.provider_id: _RetentionPolicy(RetentionActionKind.PURGE)},
        providers={},
        clock=lambda: NOW,
    )

    service.run()

    assert store.get_revision(first.id).maintenance_status == "failed"
    assert store.get_revision(second.id).maintenance_status == "purged"
    assert uow.savepoint_count >= 2
    assert uow.rollback_count >= 1


def test_retention_orchestrator_has_no_concrete_module_names() -> None:
    source = (CATALOG_ROOT / "retention.py").read_text(encoding="utf-8").casefold()
    forbidden = ("tmdb", "manual", "prowlarr", "qbittorrent")
    assert [name for name in forbidden if name in source] == []
