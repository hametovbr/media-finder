import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from pydantic import BaseModel
from sqlalchemy import func, select

from media_finder.db import migrate_to_head, session_factory
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Acquisition, DownloadClientInstance, MediaItem
from media_finder.prowlarr import ProwlarrAdapter, SearchResultCache
from media_finder.sdk.types import (
    Attribution,
    CorrelationResult,
    DownloadDestination,
    MediaKind,
    MetadataSearchResult,
    ModuleKind,
    ModuleManifest,
    NormalizedMetadata,
    Provenance,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    SubmissionResult,
)
from media_finder.ui import create_ui_app


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class EmptyConfig(BaseModel):
    pass


class BrowserProvider:
    config_model = EmptyConfig

    def __init__(self, key: str) -> None:
        self.manifest = ModuleManifest(
            key=key,
            version="1.0.0",
            contract_version="1",
            name_key=f"module.{key}.name",
            capabilities=frozenset({"movie"}),
        )

    def validate_config(self) -> None:
        return None

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        return [
            MetadataSearchResult(
                provider_key=self.manifest.key,
                external_id=f"{self.manifest.key}-shared",
                kind=MediaKind.MOVIE,
                title="Shared Title",
                year=2024,
                locale=locale,
            )
        ]

    def fetch(self, kind: str, external_id: str, locale: str) -> dict[str, object]:
        return {"title": "Shared Title", "year": 2024}

    def normalize(self, payload, kind: str, external_id: str, locale: str) -> NormalizedMetadata:
        return NormalizedMetadata(
            kind=MediaKind.MOVIE,
            titles={locale: "Shared Title"},
            year=2024,
            provenance=Provenance(
                provider_key=self.manifest.key, external_id=external_id, locale=locale
            ),
        )

    def attribution(self) -> Attribution:
        return Attribution(
            provider_key=self.manifest.key,
            notice=f"Fixture data from {self.manifest.key}",
        )

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        return RetentionPolicy()

    def plan_retention(self, policy, now: datetime) -> RetentionAction:
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy, now: datetime):
        return None


class BrowserProwlarrTransport:
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "protocol": "torrent",
                "title": f"{query}.Release",
                "indexer": "Browser Indexer",
                "magnetUrl": "magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
                "guid": "browser-release",
            }
        ]

    def fetch_torrent(self, url: str) -> bytes:
        raise AssertionError("the browser fixture uses a magnet")


class BrowserClient:
    manifest = ModuleManifest(
        key="browser-client",
        version="1.0.0",
        contract_version="1",
        name_key="browser.client",
        kind=ModuleKind.DOWNLOAD_CLIENT,
        capabilities=frozenset({"magnet", "correlation"}),
    )
    config_model = EmptyConfig

    def __init__(self, destination: str) -> None:
        self.destination = destination
        self.tasks: dict[str, str] = {}

    def validate_config(self) -> None:
        return None

    def list_destinations(self) -> list[DownloadDestination]:
        return [DownloadDestination(key=self.destination, label=self.destination.upper())]

    def submit(self, artifact, destination: str, correlation: str) -> SubmissionResult:
        self.tasks[correlation] = destination
        return SubmissionResult(
            accepted=True, external_task_id="browser-task", correlation=correlation
        )

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(
            found=True,
            correlation=correlation,
            external_task_id="reconciled-task",
            conclusive=True,
        )


@dataclass(frozen=True)
class BrowserSite:
    url: str
    app: object
    pending_item_id: str


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
    clients = {"First": BrowserClient("first"), "Second": BrowserClient("second")}

    def load_client(instance: DownloadClientInstance) -> BrowserClient:
        return clients.setdefault(instance.name, BrowserClient(instance.name.casefold()))

    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        providers={
            "provider-a": BrowserProvider("provider-a"),
            "provider-b": BrowserProvider("provider-b"),
        },
        prowlarr=ProwlarrAdapter(BrowserProwlarrTransport(), SearchResultCache()),
        client_loader=load_client,
    )
    sessions = session_factory(app.state.engine)
    with sessions() as session:
        first = DownloadClientInstance(name="First", module_key="fixture", config_payload={})
        second = DownloadClientInstance(name="Second", module_key="fixture", config_payload={})
        session.add_all([first, second])
        item = MediaItem(provider_key="manual", external_id=str(uuid4()), kind="movie")
        session.add(item)
        session.flush()
        metadata = NormalizedMetadata(
            kind=MediaKind.MOVIE,
            titles={"en": "Pending Movie", "ru": "Ожидающий фильм"},
            year=2024,
            provenance=Provenance(provider_key="manual", external_id=item.external_id, locale="en"),
        )
        revision = CatalogService(session).add_revision(item, RevisionInput(normalized=metadata))
        pending = Acquisition(
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            download_client_instance_id=second.id,
            idempotency_key="pending-browser",
            naming_profile="jellyfin-v1",
            status="pending",
            destination="second",
            created_at=datetime.now(UTC),
        )
        session.add(pending)
        session.commit()
        pending_item_id = item.id

    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("browser test server did not start")
    yield BrowserSite(f"http://127.0.0.1:{port}", app, pending_item_id)
    server.should_exit = True
    thread.join(timeout=10)


def _strict_page(browser: Browser, *, locale: str = "en-US") -> tuple[Page, list[str]]:
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


def _csrf(page: Page) -> str:
    return page.locator('input[name="csrf"]').first.get_attribute("value") or ""


def test_keyboard_structured_manual_edit_specials_and_announced_completion(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(browser_site.url)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.classList.contains('skip-link')")
    page.get_by_role("link", name="Add title").click()
    page.get_by_test_id("add-mode-manual").click()
    page.get_by_label("Media type").focus()
    page.keyboard.press("End")
    page.get_by_label("Title", exact=True).focus()
    page.keyboard.type("Keyboard Series")
    page.get_by_label("Season number").fill("0")
    page.get_by_label("Episode number").fill("1")
    page.get_by_label("Episode title").fill("Pilot Special")
    page.get_by_role("button", name="Save Manual metadata").focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/items/**?saved=1")
    assert page.get_by_role("status").inner_text() == "Title saved."
    assert page.evaluate("document.activeElement.id") == "ui-feedback"
    assert page.get_by_text("Season 00").is_visible()
    assert page.get_by_text(re.compile("Pilot Special")).is_visible()

    page.get_by_role("link", name="Edit metadata").click()
    page.get_by_label("Title", exact=True).fill("Edited Keyboard Series")
    page.get_by_role("button", name="Save Manual metadata").click()
    assert page.get_by_test_id("manual-revision-confirmation").is_visible()
    page.get_by_role("button", name="Create revision").click()
    page.wait_for_url("**/items/**?saved=1")
    assert page.get_by_role("heading", name="Edited Keyboard Series").is_visible()
    _axe(page, browser_site)
    assert failures == []
    page.context.close()


def test_grouped_provider_duplicate_and_similarity_confirmation(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)

    def search() -> None:
        page.goto(f"{browser_site.url}/add")
        page.get_by_label("Query").fill("Shared")
        page.get_by_role("button", name="Search", exact=True).click()
        page.get_by_test_id("provider-results-provider-a").wait_for()
        page.get_by_test_id("provider-results-provider-b").wait_for()

    search()
    page.get_by_test_id("provider-results-provider-a").get_by_role(
        "button", name="Select and confirm"
    ).click()
    page.wait_for_url("**/items/**?saved=1")

    search()
    page.get_by_test_id("provider-results-provider-a").get_by_role(
        "button", name="Select and confirm"
    ).click()
    page.wait_for_url("**?duplicate=1")
    assert page.get_by_role("status").inner_text() == "This title already exists."

    search()
    page.get_by_test_id("provider-results-provider-b").get_by_role(
        "button", name="Select and confirm"
    ).click()
    assert page.get_by_test_id("similarity-warning").is_visible()
    page.get_by_role("button", name="Add as a separate identity").click()
    page.wait_for_url("**/items/**?saved=1")
    _axe(page, browser_site)
    assert failures == []
    page.context.close()


def test_release_client_switch_idempotent_submit_and_pending_reconcile(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(f"{browser_site.url}/items/{browser_site.pending_item_id}/releases")
    page.get_by_label("Free query").fill("Pending Movie")
    page.get_by_role("button", name="Search torrents").click()
    page.get_by_test_id("release-result").get_by_role("radio").check()
    page.get_by_test_id("client-select").select_option(label="Second")
    page.get_by_test_id("destination-select").wait_for()
    assert page.get_by_test_id("destination-select").input_value() == "second"
    payload = {
        "csrf": _csrf(page),
        "release_token": page.get_by_test_id("release-result")
        .get_by_role("radio")
        .get_attribute("value"),
        "client_instance_id": page.get_by_test_id("client-select").input_value(),
        "destination": "second",
        "idempotency_key": page.locator('input[name="idempotency_key"]').input_value(),
    }
    page.get_by_test_id("submit-acquisition").click()
    page.wait_for_url("**?acquisition=submitted")
    assert page.get_by_role("status").inner_text() == "Submitted"
    repeated = page.request.post(
        f"{browser_site.url}/ui/items/{browser_site.pending_item_id}/acquisitions",
        form=payload,
        max_redirects=0,
    )
    assert repeated.status == 303

    page.goto(f"{browser_site.url}/items/{browser_site.pending_item_id}")
    page.get_by_test_id("detail-tab-acquisitions").click()
    assert "progress" not in page.locator("#detail-panel").inner_text().casefold()
    page.get_by_role("button", name="Reconcile now").click()
    page.wait_for_url("**?reconciled=submitted")
    assert page.get_by_role("status").inner_text() == "Submitted"
    sessions = session_factory(browser_site.app.state.engine)
    with sessions() as database:
        assert (
            database.scalar(
                select(func.count(Acquisition.id)).where(
                    Acquisition.idempotency_key == payload["idempotency_key"]
                )
            )
            == 1
        )
    _axe(page, browser_site)
    assert failures == []
    page.context.close()


def test_settings_collection_controls_russian_csrf_and_accessibility(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(f"{browser_site.url}/settings")
    checklist = page.get_by_test_id("readiness-checklist")
    assert "Ready: Prowlarr" in checklist.inner_text()
    assert "Ready: First" in checklist.inner_text()
    client_form = page.get_by_test_id("client-module-qbittorrent")
    client_form.get_by_label("Instance name").fill("Third")
    client_form.get_by_label("Base URL").fill("https://qb.example.test")
    client_form.get_by_label("Username environment reference").fill("env:QB_USERNAME")
    client_form.get_by_label("Password environment reference").fill("env:QB_PASSWORD")
    client_form.get_by_role("button", name="Save").click()
    page.wait_for_url("**/settings?saved=1")
    assert page.get_by_role("status").inner_text() == "Settings saved."
    assert page.evaluate("document.activeElement.id") == "ui-feedback"
    assert "Ready: Third" in page.get_by_test_id("readiness-checklist").inner_text()

    page.get_by_label("New collection").fill("Browser Collection")
    page.get_by_role("button", name="Create collection").click()
    page.wait_for_url(browser_site.url + "/")
    page.get_by_role("link", name="Pending Movie").click()
    page.get_by_test_id("move-item").get_by_label("Collection").select_option(
        label="Browser Collection"
    )
    page.get_by_test_id("move-item").get_by_role("button", name="Move title").click()
    page.get_by_role("button", name="Archive", exact=True).click()
    page.goto(f"{browser_site.url}/?archived=1")
    page.get_by_role("button", name="Restore title").click()
    page.get_by_role("button", name=re.compile("Archive collection: Browser Collection")).click()
    page.goto(f"{browser_site.url}/?archived=1")
    page.get_by_role("button", name="Restore collection").click()

    page.goto(f"{browser_site.url}/about")
    assert "Fixture data from provider-a" in page.locator("main").inner_text()
    page.get_by_test_id("locale-switcher").select_option("ru")
    page.wait_for_load_state("networkidle")
    page.goto(f"{browser_site.url}/add/manual")
    critical = page.locator("main").inner_text()
    for english in (
        "Create Manual title",
        "Common metadata",
        "Media type",
        "Save Manual metadata",
    ):
        assert english not in critical
    rejected = page.request.post(f"{browser_site.url}/ui/collections", form={"name": "No CSRF"})
    assert rejected.status == 403
    assert 'data-error-code="csrf_invalid"' in rejected.text()
    assert "Запрос отклонён." in rejected.text()
    _axe(page, browser_site)
    assert failures == []
    page.context.close()
