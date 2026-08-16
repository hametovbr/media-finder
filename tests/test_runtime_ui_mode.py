from pathlib import Path
from threading import Event, Thread
from time import sleep

import pytest
from fastapi.testclient import TestClient
from media_finder.runtime import ui_mode
from media_finder_core.platform import ConfigurationError
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_application


def _environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str | None,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'mode.db'}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long production session secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "processor-token")
    monkeypatch.setenv("MEDIA_FINDER_SECURE_COOKIE", "false")
    if mode is None:
        monkeypatch.delenv("MEDIA_FINDER_UI_MODE", raising=False)
    else:
        monkeypatch.setenv("MEDIA_FINDER_UI_MODE", mode)
    migrate_to_head(database_url)


def test_ui_mode_defaults_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "test-ui-secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "test-integration-token")
    monkeypatch.delenv("MEDIA_FINDER_UI_MODE", raising=False)
    assert ui_mode() == "builtin"
    monkeypatch.setenv("MEDIA_FINDER_UI_MODE", "builtin")
    assert ui_mode() == "builtin"
    monkeypatch.setenv("MEDIA_FINDER_UI_MODE", "disabled")
    assert ui_mode() == "disabled"
    monkeypatch.setenv("MEDIA_FINDER_UI_MODE", "other")
    with pytest.raises(ConfigurationError) as invalid:
        ui_mode()
    assert invalid.value.safe_details == {"variable": "MEDIA_FINDER_UI_MODE"}
    monkeypatch.setenv("MEDIA_FINDER_UI_MODE", "BUILTIN")
    with pytest.raises(ConfigurationError):
        ui_mode()


@pytest.mark.parametrize("mode", [None, "builtin"])
def test_builtin_mode_composes_html_control_processor_and_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str | None,
) -> None:
    _environment(monkeypatch, tmp_path, mode)
    app = create_application()
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/control/v1/session").status_code == 200
        assert client.get("/api/control/openapi.json").status_code == 200
        assert client.get("/health/live").status_code == 200
        assert client.get("/api/v1/media-items/missing/metadata").status_code == 401
    assert app.state.engine is app.state.processor.state.engine


def test_disabled_mode_omits_html_but_keeps_both_apis_and_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _environment(monkeypatch, tmp_path, "disabled")
    with TestClient(create_application()) as client:
        assert client.get("/").status_code == 404
        assert client.get("/static/base.css").status_code == 404
        assert client.get("/api/control/v1/session").status_code == 200
        assert client.get("/api/v1/media-items/missing/metadata").status_code == 401
        assert client.get("/health/ready").status_code == 200


def test_root_lifespan_is_the_only_owner_and_closes_shared_resources_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _environment(monkeypatch, tmp_path, "builtin")
    monkeypatch.setattr("media_finder.runtime._execute_maintenance", lambda *_args, **_kwargs: None)
    app = create_application()
    closed = {"runtime": 0, "engine": 0}
    original_runtime_close = app.state.runtime_factory.close
    original_engine_dispose = app.state.engine.dispose

    def close_runtime() -> None:
        closed["runtime"] += 1
        original_runtime_close()

    def dispose_engine() -> None:
        closed["engine"] += 1
        original_engine_dispose()

    monkeypatch.setattr(app.state.runtime_factory, "close", close_runtime)
    monkeypatch.setattr(app.state.engine, "dispose", dispose_engine)

    assert app.state.processor.state.owns_engine is False
    with TestClient(app) as client:
        assert client.get("/api/control/v1/session").status_code == 200

    assert closed == {"runtime": 1, "engine": 1}


def test_shutdown_waits_for_inflight_maintenance_before_disposing_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _environment(monkeypatch, tmp_path, "builtin")
    started = Event()
    completed = Event()
    allow_finish = Event()
    exited = Event()
    disposed_after_completion: list[bool] = []

    def slow_maintenance(*_: object, **__: object) -> None:
        started.set()
        assert allow_finish.wait(timeout=2)
        completed.set()

    monkeypatch.setattr("media_finder.runtime._execute_maintenance", slow_maintenance)
    app = create_application()
    original_dispose = app.state.engine.dispose

    def dispose_engine() -> None:
        disposed_after_completion.append(completed.is_set())
        original_dispose()

    monkeypatch.setattr(app.state.engine, "dispose", dispose_engine)

    def run_lifespan() -> None:
        with TestClient(app):
            pass
        exited.set()

    thread = Thread(target=run_lifespan)
    thread.start()
    assert started.wait(timeout=1)
    sleep(0.05)
    try:
        assert not exited.is_set()
    finally:
        allow_finish.set()
        thread.join(timeout=2)

    assert completed.is_set()
    assert exited.is_set()
    assert disposed_after_completion == [True]
