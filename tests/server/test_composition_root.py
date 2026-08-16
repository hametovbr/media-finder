"""Executable requirements for the server-owned production resource graph."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_core.platform import migrate_to_head
from media_finder_sdk import ReleaseProvider
from media_finder_server import (
    create_application,
    create_legacy_module_registry,
    create_runtime_factory,
)
from media_finder_server import modules as server_modules
from media_finder_server import runtime as server_runtime
from media_finder_server.integration_runtime import DefaultRuntimeFactory

ROOT = Path(__file__).parents[2]
HOST = ROOT / "apps" / "server" / "src" / "media_finder_server"
PRODUCTION_ROOTS = (
    ROOT / "apps" / "server" / "src" / "media_finder",
    ROOT / "packages" / "core" / "src" / "media_finder_core",
    ROOT / "packages" / "builtin-ui" / "src" / "media_finder_builtin_ui",
)
SHARED_CONSTRUCTORS = {
    "BackendBrowserSecurity",
    "DefaultRuntimeFactory",
    "EphemeralCache",
    "MaintenanceRunner",
    "ModuleRuntime",
    "ReleaseSelectionCache",
    "SqlAlchemyMaintenanceState",
    "create_database",
    "session_factory",
}
LOCAL_CONSTRUCTOR_CALLS = {
    (
        "packages/core/src/media_finder_core/platform/database.py",
        "create_database",
    ),
}


def _called_name(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    ui_mode: str,
    filename: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / filename}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.setenv(
        "MEDIA_FINDER_UI_SECRET",
        "a sufficiently long server composition secret",
    )
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "composition-token")
    monkeypatch.setenv("MEDIA_FINDER_SECURE_COOKIE", "false")
    monkeypatch.setenv("MEDIA_FINDER_UI_MODE", ui_mode)
    migrate_to_head(database_url)


class _RecordingReleaseCache(ReleaseSelectionCache):
    clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1
        super().clear()


def test_application_shell_allocates_nothing_before_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch create_application eagerly acquiring resources that may never be served."""

    allocated = False

    def unexpected_resource(*_: object, **__: object) -> object:
        nonlocal allocated
        allocated = True
        raise AssertionError("shell_allocated_resource")

    for name in (
        "create_database",
        "ReleaseSelectionCache",
        "EphemeralCache",
        "BackendBrowserSecurity",
        "MaintenanceRunner",
        "create_runtime_module_composition",
    ):
        monkeypatch.setattr(server_runtime, name, unexpected_resource)

    application = create_application(environment={}, http_client_factory=unexpected_resource)

    assert allocated is False
    assert getattr(application.state, "resources", None) is None


def test_compatibility_factory_borrows_release_selection_service() -> None:
    """Catch compatibility cleanup duplicating the service owner's cache close."""

    cache = _RecordingReleaseCache()
    selections = ReleaseSelectionService(
        provider=cast(ReleaseProvider, object()),
        cache=cache,
    )
    factory = DefaultRuntimeFactory(
        registry=create_legacy_module_registry(),
        environment={},
        release_selections=selections,
    )

    factory.close()
    factory.close()
    assert cache.clear_calls == 0

    selections.close()
    assert cache.clear_calls == 1


def test_production_control_uses_no_legacy_registry_or_runtime_adapters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch the production graph restoring legacy registry/runtime construction."""

    _configure(monkeypatch, tmp_path, ui_mode="disabled", filename="typed-control.db")

    def legacy_used(*_: object, **__: object) -> object:
        raise AssertionError("legacy_control_adapter_used")

    monkeypatch.setattr(server_modules, "create_legacy_registry", legacy_used)
    monkeypatch.setattr(
        "media_finder_server.integration_runtime.DefaultRuntimeFactory.__init__",
        legacy_used,
    )
    monkeypatch.setattr(
        "media_finder_server.integration_runtime.RuntimeResolver.__init__",
        legacy_used,
    )

    application = create_application()
    with TestClient(application):
        resources = application.state.resources
        assert resources.registry is resources.module_runtime.registry
        assert not hasattr(resources, "legacy_registry")
        assert not hasattr(resources, "runtime_factory")
        assert not hasattr(resources, "runtime")


@pytest.mark.parametrize(
    ("module_environment", "expected"),
    [
        (
            {},
            {
                "manual": None,
                "tmdb": "integration_environment_missing",
                "prowlarr": "module_environment_missing",
                "qbittorrent": "module_environment_missing",
            },
        ),
        (
            {
                "TMDB_TOKEN": "invalid-tmdb-token",
                "PROWLARR_URL": "https://prowlarr.example.test",
                "PROWLARR_API_KEY": "invalid-prowlarr-key",
                "QBITTORRENT_URL": "https://qb.example.test",
                "QBITTORRENT_USERNAME": "invalid-user",
                "QBITTORRENT_PASSWORD": "invalid-password",
            },
            {
                "manual": None,
                "tmdb": "metadata_provider_configuration_invalid",
                "prowlarr": "prowlarr_configuration_invalid",
                "qbittorrent": "download_client_authentication_failed",
            },
        ),
    ],
)
def test_typed_diagnostics_preserve_frozen_compatibility_codes(
    tmp_path: Path,
    module_environment: dict[str, str],
    expected: dict[str, str | None],
) -> None:
    """Catch typed SDK failures leaking through the stable browser control contract."""

    database_url = f"sqlite:///{tmp_path / f'diagnostics-{len(module_environment)}.db'}"
    migrate_to_head(database_url)
    environment = {
        "MEDIA_FINDER_DATABASE_URL": database_url,
        "MEDIA_FINDER_UI_SECRET": "a sufficiently long diagnostics contract secret",
        "MEDIA_FINDER_INTEGRATION_TOKEN": "diagnostics-token",
        "MEDIA_FINDER_SECURE_COOKIE": "false",
        "MEDIA_FINDER_UI_MODE": "disabled",
        **module_environment,
    }

    def client_factory() -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.themoviedb.org":
                return httpx.Response(500, text="invalid")
            if request.url.host == "prowlarr.example.test":
                return httpx.Response(500, text="invalid")
            if request.url.host == "qb.example.test":
                return httpx.Response(200, text="Fails.")
            return httpx.Response(404)

        return httpx.Client(transport=httpx.MockTransport(handler))

    compatibility = create_runtime_factory(
        environment=environment,
        http_client_factory=client_factory,
    )
    try:
        frozen = {
            "manual": None,
            "tmdb": compatibility.metadata_provider("tmdb").error_code,
            "prowlarr": compatibility.release_selections().error_code,
            "qbittorrent": compatibility.selected_download_client().error_code,
        }
    finally:
        compatibility.close()
    assert frozen == expected

    application = create_application(
        environment=environment,
        http_client_factory=client_factory,
    )
    with TestClient(application) as client:
        response = client.get("/api/control/v1/integrations")
        assert response.status_code == 200
        typed = {item["key"]: item["error_code"] for item in response.json()}
    assert typed == expected


def test_release_selection_cache_has_one_normal_shutdown_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch two root resources both clearing the same release-selection cache."""

    _configure(monkeypatch, tmp_path, ui_mode="disabled", filename="one-cache-owner.db")
    caches: list[_RecordingReleaseCache] = []

    def recording_cache() -> _RecordingReleaseCache:
        cache = _RecordingReleaseCache()
        caches.append(cache)
        return cache

    monkeypatch.setattr(server_runtime, "ReleaseSelectionCache", recording_cache)

    with TestClient(create_application()):
        pass

    assert len(caches) == 1
    assert caches[0].clear_calls == 1


def test_shared_application_infrastructure_is_constructed_only_by_the_server_host() -> None:
    """Catch a child adapter restoring an implicit database/cache/runtime owner."""

    violations: list[str] = []
    for source_root in PRODUCTION_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node)
                relative = path.relative_to(ROOT).as_posix()
                if name in SHARED_CONSTRUCTORS and (relative, name) not in LOCAL_CONSTRUCTOR_CALLS:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")

    assert HOST.is_dir(), "the production server host package is missing"
    assert violations == [], (
        "shared resources must be constructed by media_finder_server and injected into "
        f"child packages: {violations}"
    )


@pytest.mark.parametrize("ui_mode", ["builtin", "disabled"])
def test_one_resource_graph_is_reused_by_every_delivery_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ui_mode: str,
) -> None:
    """Catch health/control/processor/UI assembly from independent resource trees."""

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode=ui_mode,
        filename=f"resource-graph-{ui_mode}.db",
    )

    application = create_application()
    with TestClient(application):
        resources = getattr(application.state, "resources", None)

        assert resources is not None, "the root app must expose its single owned resource graph"
        assert resources.engine is application.state.engine
        assert resources.sessions is application.state.sessions
        assert resources.registry is resources.module_runtime.registry
        assert resources.gateway is resources.control_app.state.gateway
        assert resources.security is resources.control_app.state.security
        assert resources.engine is resources.processor_app.state.engine
        assert resources.sessions is resources.processor_app.state.sessions
        assert resources.maintenance_runner is application.state.maintenance_runner
        assert isinstance(resources.control_app, FastAPI)
        assert isinstance(resources.processor_app, FastAPI)

        if ui_mode == "builtin":
            assert isinstance(resources.ui_app, FastAPI)
            assert resources.ui_app.state.gateway is resources.gateway
        else:
            assert resources.ui_app is None


def test_control_caches_are_injected_instead_of_created_by_child_services(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch a control-service default silently creating a second token store."""

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode="builtin",
        filename="injected-caches.db",
    )

    def implicit_cache(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("control_child_created_ephemeral_cache")

    monkeypatch.setattr(
        "media_finder_core.control.metadata.EphemeralCache",
        implicit_cache,
    )

    application = create_application()
    with TestClient(application):
        resources = getattr(application.state, "resources", None)

        assert resources is not None
        assert resources.metadata_selections is not None
        assert resources.manual_drafts is not None


def test_separate_composition_attempts_do_not_share_mutable_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch process-global engines, sessions, runtimes, or bounded caches."""

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode="disabled",
        filename="first-attempt.db",
    )
    first = create_application()

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode="disabled",
        filename="second-attempt.db",
    )
    second = create_application()

    with TestClient(first), TestClient(second):
        first_resources = getattr(first.state, "resources", None)
        second_resources = getattr(second.state, "resources", None)
        assert first_resources is not None
        assert second_resources is not None
        assert first_resources is not second_resources
        assert first_resources.engine is not second_resources.engine
        assert first_resources.sessions is not second_resources.sessions
        assert first_resources.module_runtime is not second_resources.module_runtime
        assert first_resources.metadata_selections is not second_resources.metadata_selections
        assert first_resources.manual_drafts is not second_resources.manual_drafts


def test_concurrent_composition_and_module_attempts_remain_attempt_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch host-global graphs or host-side module construction serialization."""

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode="disabled",
        filename="concurrent-template.db",
    )
    environments: list[dict[str, str]] = []
    for index in range(2):
        database_url = f"sqlite:///{tmp_path / f'concurrent-{index}.db'}"
        migrate_to_head(database_url)
        environments.append(
            {
                "MEDIA_FINDER_DATABASE_URL": database_url,
                "MEDIA_FINDER_UI_SECRET": "a sufficiently long server composition secret",
                "MEDIA_FINDER_INTEGRATION_TOKEN": "composition-token",
                "MEDIA_FINDER_SECURE_COOKIE": "false",
                "MEDIA_FINDER_UI_MODE": "disabled",
            }
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = tuple(
            executor.map(lambda value: create_application(environment=value), environments)
        )

    with TestClient(attempts[0]), TestClient(attempts[1]):
        first_resources = attempts[0].state.resources
        second_resources = attempts[1].state.resources
        assert first_resources is not second_resources
        assert first_resources.module_runtime is not second_resources.module_runtime

        with ThreadPoolExecutor(max_workers=2) as executor:
            providers = tuple(
                executor.map(
                    lambda _: first_resources.module_runtime.metadata_provider("manual"),
                    range(2),
                )
            )
        assert providers[0] is providers[1]


def test_root_lifespan_still_disposes_database_after_module_shutdown_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch a partial shutdown abandoning lower-level root-owned resources."""

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode="disabled",
        filename="shutdown-failure.db",
    )
    application = create_application()
    events: list[str] = []

    with pytest.raises(RuntimeError, match="module shutdown failed"), TestClient(application):
        resources = application.state.resources
        original_module_close = resources.module_runtime.close
        original_engine_dispose = resources.engine.dispose

        def close_modules_with_failure() -> None:
            events.append("modules")
            original_module_close()
            raise RuntimeError("module shutdown failed")

        def dispose_database() -> None:
            events.append("database")
            original_engine_dispose()

        monkeypatch.setattr(
            resources.module_runtime,
            "close",
            close_modules_with_failure,
        )
        monkeypatch.setattr(resources.engine, "dispose", dispose_database)

    assert events == ["modules", "database"]


def test_partial_construction_failure_preserves_root_error_and_cleans_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catch adapter construction failures leaking the attempt-local module/database graph."""

    _configure(
        monkeypatch,
        tmp_path,
        ui_mode="disabled",
        filename="construction-failure.db",
    )
    events: list[str] = []
    caches: list[_RecordingReleaseCache] = []
    original_create_database = server_runtime.create_database  # type: ignore[attr-defined]
    original_module_composition = (  # type: ignore[attr-defined]
        server_runtime.create_runtime_module_composition
    )

    def tracked_database(url: str):  # type: ignore[no-untyped-def]
        engine = original_create_database(url)
        original_dispose = engine.dispose

        def dispose() -> None:
            events.append("database")
            original_dispose()

        monkeypatch.setattr(engine, "dispose", dispose)
        return engine

    def tracked_modules(**options: object):  # type: ignore[no-untyped-def]
        composition = original_module_composition(**options)  # type: ignore[arg-type]
        original_close = composition.runtime.close

        def close_with_failure() -> None:
            events.append("modules")
            original_close()
            raise RuntimeError("cleanup failure")

        monkeypatch.setattr(composition.runtime, "close", close_with_failure)
        return composition

    def recording_cache() -> _RecordingReleaseCache:
        cache = _RecordingReleaseCache()
        caches.append(cache)
        return cache

    monkeypatch.setattr(server_runtime, "create_database", tracked_database)
    monkeypatch.setattr(
        server_runtime,
        "create_runtime_module_composition",
        tracked_modules,
    )
    monkeypatch.setattr(server_runtime, "ReleaseSelectionCache", recording_cache)
    monkeypatch.setattr(
        server_runtime,
        "create_control_app",
        lambda **_: (_ for _ in ()).throw(RuntimeError("control adapter failed")),
    )

    application = create_application()
    with pytest.raises(RuntimeError, match="control adapter failed"), TestClient(application):
        pass

    assert events == ["modules", "database"]
    assert len(caches) == 1
    assert caches[0].clear_calls == 1
