from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from media_finder import runtime as legacy_runtime
from media_finder.models import AppSetting
from media_finder_core.platform.configuration import ConfigurationError
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_application, run


def test_environment_application_serves_ui_health_and_protected_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long production session secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "processor-token")
    monkeypatch.setenv("MEDIA_FINDER_SECURE_COOKIE", "false")
    migrate_to_head(database_url)

    with TestClient(create_application()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health/live").json() == {"status": "live"}
        denied = client.get("/api/v1/media-items/missing/metadata")
        assert denied.status_code == 401
        missing = client.get(
            "/api/v1/media-items/missing/metadata",
            headers={"Authorization": "Bearer processor-token"},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "media_item_not_found"


def test_runtime_lifespan_executes_generic_startup_maintenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'maintenance.db'}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long production session secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "processor-token")
    migrate_to_head(database_url)
    app = create_application()

    with TestClient(app):
        deadline = monotonic() + 2
        completed = None
        while monotonic() < deadline:
            with app.state.sessions() as session:
                completed = session.get(AppSetting, "maintenance.last_completed")
            if completed is not None:
                break
            sleep(0.01)

    assert completed is not None


def test_runtime_lifespan_disposes_database_after_module_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'close-failure.db'}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long production session secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "processor-token")
    migrate_to_head(database_url)
    app = create_application()
    disposed = False
    original_dispose = app.state.engine.dispose
    original_close = app.state.runtime_factory.close

    def dispose() -> None:
        nonlocal disposed
        disposed = True
        original_dispose()

    def close_with_failure() -> None:
        original_close()
        raise RuntimeError("module close failed")

    monkeypatch.setattr(app.state.engine, "dispose", dispose)
    monkeypatch.setattr(app.state.runtime_factory, "close", close_with_failure)

    with pytest.raises(RuntimeError, match="module close failed"), TestClient(app):
        pass

    assert disposed is True


def test_application_validates_configuration_before_constructing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'construction-failure.db'}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.delenv("MEDIA_FINDER_UI_SECRET", raising=False)
    migrate_to_head(database_url)
    created = False

    def create_recorded_database(url: str):
        del url
        nonlocal created
        created = True
        raise AssertionError("database must not be constructed")

    monkeypatch.setattr(legacy_runtime, "create_database", create_recorded_database)

    with pytest.raises(ConfigurationError) as failure:
        create_application()

    assert failure.value.safe_details == {"variable": "MEDIA_FINDER_UI_SECRET"}
    assert created is False


def test_run_migrates_before_starting_exactly_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", "sqlite:////data/media-finder.db")
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "test-ui-secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "test-integration-token")
    monkeypatch.setattr(
        "media_finder.runtime.migrate_to_head",
        lambda url: events.append(("migrate", url)),
    )
    application = object()
    monkeypatch.setattr(
        "media_finder.runtime.create_application",
        lambda **_: events.append("create") or application,
    )
    monkeypatch.setattr(
        "media_finder.runtime.uvicorn.run",
        lambda app, **kwargs: events.append(("serve", app, kwargs)),
    )

    run()

    assert events == [
        ("migrate", "sqlite:////data/media-finder.db"),
        "create",
        (
            "serve",
            application,
            {"host": "0.0.0.0", "port": 8000, "workers": 1, "proxy_headers": True},
        ),
    ]


def test_migration_failure_prevents_server_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_migration(_: str) -> None:
        raise RuntimeError("migration failed")

    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", "sqlite:////data/media-finder.db")
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "test-ui-secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "test-integration-token")
    monkeypatch.setattr("media_finder.runtime.migrate_to_head", fail_migration)
    served = False

    def serve(*args: object, **kwargs: object) -> None:
        del args, kwargs
        nonlocal served
        served = True

    monkeypatch.setattr("media_finder.runtime.uvicorn.run", serve)

    with pytest.raises(RuntimeError, match="migration failed"):
        run()

    assert served is False
