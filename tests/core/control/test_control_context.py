"""RED contracts for the framework-neutral control bounded context."""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from media_finder_control import (
    AcquisitionStatus,
    ControlFailure,
    ControlGateway,
    Locale,
    MediaKind,
    Page,
    PageRequest,
)
from media_finder_control.manual import ManualDocumentV1
from media_finder_control.models import (
    AboutView,
    AcquisitionSubmissionRequest,
    AcquisitionView,
    CatalogItemView,
    CollectionView,
    DownloadDestination,
    IntegrationDiagnostic,
    ManualImportRequest,
    ManualImportResult,
    MediaItemDetail,
    MetadataSearchRequest,
    MetadataSearchResult,
    MetadataSelectionRequest,
    MetadataSelectionResult,
    MetadataView,
    ReleaseSearchRequest,
    ReleaseSearchResult,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).parents[3]
CONTROL_ROOT = ROOT / "packages" / "core" / "src" / "media_finder_core" / "control"
MODULES = ("catalog", "metadata", "acquisition", "diagnostics", "facade", "security")
CONTROL_FILES = (*(f"{name}.py" for name in MODULES), "__init__.py")


def _api() -> SimpleNamespace:
    modules: dict[str, object] = {}
    missing: list[str] = []
    for name in MODULES:
        try:
            modules[name] = importlib.import_module(f"media_finder_core.control.{name}")
        except ModuleNotFoundError as error:
            if (
                error.name == f"media_finder_core.control.{name}"
                or error.name == "media_finder_core.control"
            ):
                missing.append(name)
            else:
                raise

    required = {
        "CatalogControlService": getattr(modules.get("catalog"), "CatalogControlService", None),
        "MetadataControlService": getattr(modules.get("metadata"), "MetadataControlService", None),
        "AcquisitionControlService": getattr(
            modules.get("acquisition"), "AcquisitionControlService", None
        ),
        "DiagnosticsControlService": getattr(
            modules.get("diagnostics"), "DiagnosticsControlService", None
        ),
        "ControlFacade": getattr(modules.get("facade"), "ControlFacade", None),
    }
    missing.extend(name for name, value in required.items() if value is None)
    assert missing == [], f"control bounded-context boundaries are missing: {sorted(missing)}"
    return SimpleNamespace(**required, **modules)


def _item_detail() -> MediaItemDetail:
    return MediaItemDetail(
        id="item-1",
        provider_key="provider-a",
        external_id="external-1",
        kind=MediaKind.MOVIE,
        metadata=MetadataView(kind=MediaKind.MOVIE, titles={"en": "Example"}),
    )


class _CatalogApplication:
    def list_collections(self, *, page: PageRequest, archived: bool) -> Page[CollectionView]:
        assert page.limit == 1
        assert page.cursor == "collections-after-1"
        assert archived is False
        return Page(
            items=(CollectionView(id="collection-2", name="Second"),),
            next_cursor="collections-after-2",
        )

    def create_collection(self, *, name: str) -> CollectionView:
        assert name == "First"
        return CollectionView(id="collection-1", name=name)

    def change_collection(self, *, collection_id: str, archived: bool) -> CollectionView:
        assert collection_id == "collection-1"
        return CollectionView(id=collection_id, name="First", archived=archived)

    def list_media_items(
        self,
        *,
        locale: Locale,
        page: PageRequest,
        collection_id: str | None,
        uncategorized: bool,
        archived: bool,
    ) -> Page[CatalogItemView]:
        assert locale is Locale.EN
        assert page == PageRequest(limit=1)
        assert collection_id is None
        assert uncategorized is True
        assert archived is False
        return Page(
            items=(
                CatalogItemView(
                    id="item-1",
                    title="Example",
                    kind=MediaKind.MOVIE,
                    provider_key="provider-a",
                ),
            ),
            next_cursor=None,
        )

    def get_media_item(self, *, item_id: str, locale: Locale) -> MediaItemDetail:
        assert item_id == "item-1"
        assert locale is Locale.EN
        return _item_detail()

    def change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail:
        assert item_id == "item-1"
        assert collection_id is None
        assert archived is True
        assert locale is Locale.EN
        return _item_detail().model_copy(update={"archived": True})


class _MetadataApplication:
    def __init__(self) -> None:
        self._metadata_token = "metadata-selection"
        self._manual_token = "manual-confirmation"

    def metadata_providers(self) -> tuple[object, ...]:
        return ()

    def search_metadata(
        self, *, request: MetadataSearchRequest
    ) -> tuple[MetadataSearchResult, ...]:
        assert request.query == "Example"
        assert request.locale is Locale.EN
        return (
            MetadataSearchResult(
                token=self._metadata_token,
                provider_key="provider-a",
                external_id="external-1",
                kind=MediaKind.MOVIE,
                title="Example",
                locale=Locale.EN,
            ),
        )

    def select_metadata(
        self,
        *,
        token: str,
        request: MetadataSelectionRequest,
        locale: Locale,
    ) -> MetadataSelectionResult:
        assert request.confirm_similarity is True
        assert locale is Locale.EN
        if token != self._metadata_token:
            raise ControlFailure(code="selection_expired", status=410)
        self._metadata_token = "consumed"
        return MetadataSelectionResult(item=_item_detail(), created=True)

    def import_manual(
        self, *, request: ManualImportRequest, confirmation_token: str | None
    ) -> ManualImportResult:
        assert request.document.titles == {"en": "Manual"}
        if confirmation_token is None:
            return ManualImportResult(confirmation_token=self._manual_token)
        if confirmation_token != self._manual_token:
            raise ControlFailure(code="selection_expired", status=410)
        self._manual_token = "consumed"
        return ManualImportResult(item=_item_detail(), created=True)

    def edit_manual(
        self, *, item_id: str, document: ManualDocumentV1, confirmation_token: str | None
    ) -> ManualImportResult:
        raise AssertionError("not part of this focused contract")

    def confirm_manual(self, *, token: str) -> ManualImportResult:
        raise AssertionError("not part of this focused contract")

    def import_episodes(self, *, item_id: str, request: object, locale: Locale) -> MediaItemDetail:
        raise AssertionError("not part of this focused contract")


class _AcquisitionApplication:
    def __init__(self) -> None:
        self._by_key: dict[str, AcquisitionView] = {}

    def search_releases(
        self, *, item_id: str, request: ReleaseSearchRequest
    ) -> tuple[ReleaseSearchResult, ...]:
        raise AssertionError("not part of this focused contract")

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (DownloadDestination(key="destination-a", label="Destination A"),)

    def submit_acquisition(self, *, request: AcquisitionSubmissionRequest) -> AcquisitionView:
        if request.idempotency_key not in self._by_key:
            self._by_key[request.idempotency_key] = AcquisitionView(
                id="acquisition-1",
                media_item_id=request.media_item_id,
                status=AcquisitionStatus.PENDING,
                release_title="Example release",
                destination=request.destination,
                created_at=NOW,
            )
        return self._by_key[request.idempotency_key]

    def reconcile_acquisition(self, *, acquisition_id: str) -> AcquisitionView:
        assert acquisition_id == "acquisition-1"
        pending = next(iter(self._by_key.values()))
        return pending.model_copy(update={"status": AcquisitionStatus.SUBMITTED})


class _DiagnosticsApplication:
    def integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]:
        raise RuntimeError("upstream credentials=https://operator:secret@example.test/api")

    def about(self) -> AboutView:
        return AboutView(version="0.1.0")


def test_control_context_exposes_the_required_shallow_public_boundaries() -> None:
    """Removing a bounded service or facade breaks the planned public control seam."""
    api = _api()

    exported = importlib.import_module("media_finder_core.control")
    assert {
        "CatalogControlService",
        "MetadataControlService",
        "AcquisitionControlService",
        "DiagnosticsControlService",
        "ControlFacade",
    } <= set(exported.__all__)
    assert all(
        callable(getattr(api, name)) for name in exported.__all__ if name.endswith("Service")
    )


def test_catalog_control_service_preserves_control_dtos_and_continuation_cursor_with_a_fake() -> (
    None
):
    """Catalog control requires narrow ports and core-owned signed continuation cursors."""
    api = _api()
    parameters = inspect.signature(api.CatalogControlService).parameters
    assert {
        "query_port",
        "unit_of_work",
        "projector",
        "cursor_secret",
        "clock",
    } <= set(parameters)
    assert "application" not in parameters
    codec = api.security.CursorCodec(secret=b"control-context-test-secret")
    token = codec.encode(
        resource="collections", filters={"archived": False}, position=("First", "1")
    )
    assert codec.decode(token, resource="collections", filters={"archived": False}) == (
        "First",
        "1",
    )


def test_metadata_control_service_consumes_metadata_and_manual_confirmation_tokens_once() -> None:
    """Metadata control explicitly owns its bounded selection and Manual draft stores."""
    api = _api()
    parameters = inspect.signature(api.MetadataControlService).parameters
    assert {
        "query_port",
        "unit_of_work",
        "modules",
        "projector",
        "metadata_selections",
        "manual_drafts",
    } <= set(parameters)
    assert "application" not in parameters
    manual = ManualDocumentV1(kind=MediaKind.MOVIE, locale=Locale.EN, titles={"en": "Manual"})
    draft = api.metadata.ManualDraft(
        operation="import", request=ManualImportRequest(document=manual)
    )
    from media_finder_core.platform import EphemeralCache, EphemeralTokenExpired

    cache = EphemeralCache()
    token = cache.put(draft)
    assert cache.pop(token) == draft
    with pytest.raises(EphemeralTokenExpired):
        cache.pop(token)


def test_acquisition_control_service_preserves_idempotency_and_reconciles() -> None:
    """Acquisition control consumes only catalog, persistence, and module capability ports."""
    api = _api()
    parameters = inspect.signature(api.AcquisitionControlService).parameters
    assert {
        "catalog_queries",
        "pinned_catalog",
        "acquisition_queries",
        "acquisition_uow",
        "modules",
        "clock",
    } <= set(parameters)
    assert "application" not in parameters
    assert getattr(api.acquisition.AcquisitionControlModules, "_is_protocol", False)


def test_diagnostics_control_service_translates_unexpected_details_to_a_stable_safe_error() -> None:
    """Leaking a module exception would expose credentials or upstream URLs."""
    api = _api()

    class Modules:
        def diagnostic_modules(self):
            raise RuntimeError("upstream credentials=https://operator:secret@example.test/api")

        def environment_is_set(self, name: str) -> bool:
            return False

        def attributions(self):
            return ()

    service = api.DiagnosticsControlService(modules=Modules(), build_version="0.1.0")

    async def scenario() -> None:
        with pytest.raises(ControlFailure) as failure:
            await service.integration_diagnostics()
        assert failure.value.error.code == "integration_diagnostics_unavailable"
        assert "secret" not in str(failure.value)
        assert await service.about() == AboutView(version="0.1.0")

    asyncio.run(scenario())


def test_control_failure_does_not_promote_an_untrusted_exception_message_to_a_code() -> None:
    """A credential-shaped exception message must never become a browser error code."""
    api = _api()

    failure = api.security.control_failure(
        RuntimeError("supersecrettoken"), "integration_diagnostics_unavailable"
    )

    assert failure.error.code == "integration_diagnostics_unavailable"
    assert "supersecrettoken" not in str(failure)


def test_control_facade_is_an_async_control_gateway_over_context_services() -> None:
    """Bypassing a context service would couple the facade to persistence or modules."""
    api = _api()

    class Catalog:
        async def create_collection(self, *, name: str) -> CollectionView:
            return CollectionView(id="collection-1", name=name)

        async def list_media_items(self, **_: object) -> Page[CatalogItemView]:
            return Page(
                items=(
                    CatalogItemView(
                        id="item-1",
                        title="Example",
                        kind=MediaKind.MOVIE,
                        provider_key="provider-a",
                    ),
                )
            )

    class Diagnostics:
        async def about(self) -> AboutView:
            return AboutView(version="0.1.0")

    facade = api.ControlFacade(
        catalog=Catalog(),
        metadata=object(),
        acquisition=object(),
        diagnostics=Diagnostics(),
    )

    protocol_methods = {
        name
        for name, value in ControlGateway.__dict__.items()
        if callable(value) and not name.startswith("_")
    }
    assert protocol_methods <= {name for name in dir(facade) if callable(getattr(facade, name))}

    async def scenario(gateway: ControlGateway) -> None:
        assert await gateway.create_collection(name="First") == CollectionView(
            id="collection-1", name="First"
        )
        page = await gateway.list_media_items(
            locale=Locale.EN,
            page=PageRequest(limit=1),
            collection_id=None,
            uncategorized=True,
            archived=False,
        )
        assert [item.title for item in page.items] == ["Example"]
        assert await gateway.about() == AboutView(version="0.1.0")

    asyncio.run(scenario(facade))


def test_control_sources_remain_framework_neutral_and_do_not_name_concrete_modules() -> None:
    """Adding a server, ORM, environment, or concrete module import breaks core portability."""
    missing_paths = [
        filename for filename in CONTROL_FILES if not (CONTROL_ROOT / filename).exists()
    ]
    assert missing_paths == [], f"control source boundaries are missing: {missing_paths}"

    forbidden_roots = {
        "fastapi",
        "media_finder",
        "media_finder_server",
        "os",
        "sqlalchemy",
        "starlette",
    }
    forbidden_prefixes = (
        "media_finder_download_",
        "media_finder_metadata_",
        "media_finder_release_",
    )
    forbidden_identifiers = {"Session", "SqlAlchemy", "sessionmaker", "DeclarativeBase", "Mapped"}
    concrete_ids = {"manual", "tmdb", "prowlarr", "qbittorrent"}
    violations: list[str] = []
    for filename in CONTROL_FILES:
        path = CONTROL_ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
            for module in imported:
                root = module.split(".", 1)[0]
                if root in forbidden_roots or module.startswith(forbidden_prefixes):
                    violations.append(f"{path.name}:{node.lineno}:{module}")
                if module.endswith(".persistence"):
                    violations.append(f"{path.name}:{node.lineno}:{module}")
            if isinstance(node, ast.Name) and node.id in forbidden_identifiers:
                violations.append(f"{path.name}:{node.lineno}:{node.id}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.casefold() in concrete_ids
            ):
                violations.append(f"{path.name}:{node.lineno}:{node.value}")

    assert violations == []


def test_server_gateway_is_only_narrow_composition_without_control_orchestration() -> None:
    """Retaining the old multi-context gateway in the host defeats the core boundary."""
    gateway_path = ROOT / "apps" / "server" / "src" / "media_finder_server" / "control_gateway.py"
    tree = ast.parse(gateway_path.read_text(encoding="utf-8"), filename=str(gateway_path))
    forbidden_identifiers = {
        "AcquisitionCommands",
        "CatalogCommands",
        "CatalogQueries",
        "CursorCodec",
        "ManualCatalogService",
        "MetadataCatalogService",
        "NormalizedMetadata",
    }
    public_groups = (
        {"list_collections", "create_collection", "change_collection", "list_media_items"},
        {"search_metadata", "select_metadata", "import_manual", "edit_manual"},
        {"search_releases", "list_destinations", "submit_acquisition", "reconcile_acquisition"},
        {"metadata_providers", "integration_diagnostics", "about"},
    )
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden_identifiers:
            violations.append(f"{node.lineno}:{node.id}")
        if not isinstance(node, ast.ClassDef):
            continue
        methods = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        owned_groups = sum(bool(methods & group) for group in public_groups)
        if owned_groups > 1:
            violations.append(f"{node.lineno}:{node.name}:owns-{owned_groups}-contexts")

    assert violations == []


def test_core_control_owns_cursor_tokens_drafts_projection_and_safe_mapping() -> None:
    """The host must not remain the hidden owner of portable control semantics."""
    sources = {name: (CONTROL_ROOT / f"{name}.py").read_text(encoding="utf-8") for name in MODULES}

    assert "class CursorCodec" in sources["security"]
    assert "EphemeralCache" in sources["metadata"]
    assert "class ManualDraft" in sources["metadata"]
    assert "MetadataView(" in sources["catalog"]
    assert "AcquisitionView(" in sources["catalog"]
    assert "MetadataCatalogService(" in sources["metadata"]
    assert "AcquisitionCommands(" in sources["acquisition"]
    assert "def control_failure" in sources["security"]
