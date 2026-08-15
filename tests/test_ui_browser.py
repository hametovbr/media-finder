import json
import os
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from media_finder.db import migrate_to_head, session_factory
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Acquisition, MediaItem
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder.ui import create_ui_app


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def browser() -> Browser:
    with sync_playwright() as playwright:
        yield _launch_browser(playwright)


def _launch_browser(playwright: Playwright) -> Browser:
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    bundled = Path(playwright.chromium.executable_path)
    if configured:
        return playwright.chromium.launch(executable_path=configured, headless=True)
    if bundled.exists():
        return playwright.chromium.launch(headless=True)
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if edge.exists():
        return playwright.chromium.launch(executable_path=str(edge), headless=True)
    raise RuntimeError(
        "No Chromium runtime found. Run `python -m playwright install chromium` or set "
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE."
    )


@pytest.fixture
def browser_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'browser.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long browser test secret")
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
    )
    sessions = session_factory(app.state.engine)
    with sessions() as session:
        item = MediaItem(
            provider_key="manual",
            external_id=str(uuid4()),
            kind="movie",
        )
        session.add(item)
        session.flush()
        metadata = NormalizedMetadata(
            kind=MediaKind.MOVIE,
            titles={"en": "Pending Movie", "ru": "Ожидающий фильм"},
            year=2024,
            provenance=Provenance(provider_key="manual", external_id=item.external_id, locale="en"),
        )
        revision = CatalogService(session).add_revision(item, RevisionInput(normalized=metadata))
        session.add(
            Acquisition(
                media_item_id=item.id,
                metadata_revision_id=revision.id,
                idempotency_key="pending-browser",
                naming_profile="jellyfin-v1",
                status="pending",
                destination="manual",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("browser test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def _strict_page(browser: Browser) -> tuple[Page, list[str]]:
    page = browser.new_context(locale="en-US").new_page()
    failures: list[str] = []
    page.on(
        "console",
        lambda message: (
            failures.append(f"console {message.type}: {message.text}")
            if message.type in {"warning", "error"}
            else None
        ),
    )
    page.on(
        "requestfailed",
        lambda request: failures.append(
            f"request failed: {request.method} {request.url}: {request.failure}"
        ),
    )
    return page, failures


def test_english_and_russian_keyboard_manual_flow_is_accessible(
    browser: Browser, browser_site: str
) -> None:
    page, failures = _strict_page(browser)
    page.goto(browser_site)
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.get_by_role("heading", name="Catalog").is_visible()
    assert page.get_by_test_id("pending-reconcile-notice").count() == 0
    assert "Manual reconciliation may be required." in page.locator("main").inner_text()
    assert "progress" not in page.locator("main").inner_text().casefold()

    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.classList.contains('skip-link')")
    assert page.evaluate("getComputedStyle(document.activeElement).outlineWidth") == "4px"

    switcher = page.get_by_test_id("locale-switcher")
    switcher.focus()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle")
    assert page.locator("html").get_attribute("lang") == "ru"
    assert page.get_by_role("heading", name="Каталог").is_visible()

    page.get_by_role("link", name="Добавить тайтл").click()
    textarea = page.locator('[data-testid="manual-json-form"] textarea')
    for _ in range(30):
        if textarea.evaluate("element => element === document.activeElement"):
            break
        page.keyboard.press("Tab")
    assert textarea.evaluate("element => element === document.activeElement")
    document = {
        "schema_version": "1",
        "kind": "movie",
        "locale": "ru",
        "titles": {"ru": "Browser Movie"},
    }
    serialized = json.dumps(document, ensure_ascii=False)
    page.keyboard.type(serialized)
    assert textarea.input_value() == serialized
    page.keyboard.press("Tab")
    assert page.locator('[data-testid="manual-json-form"] button').evaluate(
        "element => element === document.activeElement"
    )
    page.keyboard.press("Space")
    page.wait_for_url("**/items/**")
    assert page.get_by_role("heading", name="Browser Movie").is_visible()
    assert failures == []
    page.context.close()


def test_manual_only_first_run_and_csrf_rejection_are_explicit(
    browser: Browser, browser_site: str
) -> None:
    page, failures = _strict_page(browser)
    page.goto(f"{browser_site}/settings")
    checklist = page.get_by_test_id("readiness-checklist")
    assert checklist.is_visible()
    assert "Manual-only catalog use remains available." in checklist.inner_text()
    assert "Needs configuration: Prowlarr" in checklist.inner_text()

    rejected = page.request.post(f"{browser_site}/ui/collections", form={"name": "No CSRF"})
    assert rejected.status == 403
    assert "csrf_invalid" in rejected.text()
    assert failures == []
    page.context.close()
