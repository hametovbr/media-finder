import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway
from playwright.sync_api import Browser, Page, Playwright, sync_playwright


@dataclass(frozen=True, slots=True)
class BrowserSite:
    url: str


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


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
    raise RuntimeError("No Chromium runtime found. Run `python -m playwright install chromium`.")


@pytest.fixture(scope="module")
def browser() -> Browser:
    with sync_playwright() as playwright:
        yield _launch_browser(playwright)


@pytest.fixture
def fake_site() -> BrowserSite:
    app = create_builtin_ui(gateway=FakeControlGateway(), security=FakeBrowserSecurity())
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("fake gateway browser server did not start")
    yield BrowserSite(f"http://127.0.0.1:{port}")
    server.should_exit = True
    thread.join(timeout=10)


def _strict_page(browser: Browser, *, locale: str) -> tuple[Page, list[str]]:
    page = browser.new_context(locale=locale).new_page()
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


def _axe(page: Page, site: BrowserSite) -> None:
    page.add_script_tag(url=f"{site.url}/static/axe.min.js")
    serious = page.evaluate(
        """async () => (await axe.run(document, {resultTypes: ['violations']})).violations
        .filter(v => ['serious', 'critical'].includes(v.impact))
        .map(v => ({id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target)}))"""
    )
    assert serious == []


def test_fake_gateway_browser_preserves_locales_keyboard_axe_forms_and_feedback(
    browser: Browser,
    fake_site: BrowserSite,
) -> None:
    page, failures = _strict_page(browser, locale="ru-RU")
    page.goto(fake_site.url)
    assert page.get_by_text("Пример фильма").is_visible()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.classList.contains('skip-link')")
    _axe(page, fake_site)

    page.get_by_role("link", name="Добавить тайтл").click()
    page.get_by_test_id("add-mode-manual").click()
    assert page.get_by_test_id("manual-structured-form").is_visible()
    _axe(page, fake_site)

    page.goto(f"{fake_site.url}/items/movie-1?saved=1")
    feedback = page.locator('[role="status"][aria-live="polite"]')
    assert feedback.is_visible()
    assert feedback.get_attribute("tabindex") == "-1"
    page.get_by_test_id("locale-switcher").select_option("en")
    page.wait_for_load_state("networkidle")
    assert page.get_by_text("Example Movie").is_visible()
    _axe(page, fake_site)
    assert failures == []
    page.context.close()
