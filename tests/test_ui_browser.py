import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from acquisition_fakes import StaticAcquisitionModules
from catalog_fixtures import CatalogFixture as CatalogService
from catalog_fixtures import RevisionInput
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_core.acquisition.persistence import AcquisitionRecord as Acquisition
from media_finder_core.catalog.persistence import MediaItemRecord as MediaItem
from media_finder_core.platform.database import migrate_to_head, session_factory
from media_finder_sdk import (
    AttributionSpec,
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    MagnetArtifact,
    MediaKind,
    MetadataIdentity,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleKind,
    ModuleManifest,
    NormalizedMetadata,
    PrivateReleaseSelection,
    Provenance,
    ProviderPayload,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    SubmissionResult,
)
from media_finder_server import create_application
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from sqlalchemy import func, select
from ui_fixtures import create_ui_test_app


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class BrowserProvider:
    def __init__(self, key: str) -> None:
        self.manifest = ModuleManifest(
            module_id=key,
            module_kind=ModuleKind.METADATA_PROVIDER,
            module_version="1.0.0",
            sdk_compatibility=">=1,<2",
            contract_version="1",
            name_key=f"module.{key}.name",
            capabilities=frozenset({"search", "fetch", "normalize"}),
            translation_keys=frozenset({f"module.{key}.name", f"module.{key}.notice"}),
            attribution=AttributionSpec(notice_key=f"module.{key}.notice"),
        )

    def validate(self) -> None:
        return None

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        return (
            MetadataSearchResult(
                provider_id=self.manifest.module_id,
                external_id=f"{self.manifest.module_id}-shared",
                media_kind=MediaKind.MOVIE,
                title="Shared Title",
                year=2024,
                locale=query.locale,
            ),
        )

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        del identity
        return ProviderPayload(data={"title": "Shared Title", "year": 2024})

    def normalize(
        self,
        payload: ProviderPayload,
        identity: MetadataIdentity,
    ) -> NormalizedMetadata:
        del payload
        return NormalizedMetadata(
            kind=identity.media_kind,
            titles={identity.locale: "Shared Title"},
            year=2024,
            provenance=Provenance(
                provider_id=self.manifest.module_id,
                external_id=identity.external_id,
                locale=identity.locale,
            ),
        )

    def close(self) -> None:
        return None


class BrowserReleaseProvider:
    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title=f"{query.query}.Release",
                    indexer="Browser Indexer",
                    guid="browser-release",
                ),
                selection=PrivateReleaseSelection.from_bytes(b"browser-release"),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        assert selection.payload() == b"browser-release"
        return MagnetArtifact(uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789")

    def close(self) -> None:
        return None


class BrowserClient:
    manifest = ModuleManifest(
        module_id="browser-client",
        module_kind=ModuleKind.DOWNLOAD_CLIENT,
        module_version="1.0.0",
        sdk_compatibility=">=1,<2",
        contract_version="1",
        name_key="browser.client",
        capabilities=frozenset({"destinations", "submit", "correlation", "magnet"}),
        translation_keys=frozenset({"browser.client"}),
    )

    def __init__(self, destination: str) -> None:
        self.destination = destination
        self.tasks: dict[str, str] = {}

    def validate(self) -> None:
        return None

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (DownloadDestination(key=self.destination, label=self.destination.upper()),)

    def submit(
        self, artifact: DownloadArtifact, destination: str, correlation: str
    ) -> SubmissionResult:
        del artifact
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

    def close(self) -> None:
        return None


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
    clients = {"qBittorrent": BrowserClient("second")}

    app = create_ui_test_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        environment={
            "PROWLARR_URL": "https://prowlarr.browser.test",
            "PROWLARR_API_KEY": "browser-prowlarr-secret",
            "QBITTORRENT_URL": "https://qbittorrent.browser.test",
            "QBITTORRENT_USERNAME": "browser-user",
            "QBITTORRENT_PASSWORD": "browser-password",
        },
        providers={
            "provider-a": BrowserProvider("provider-a"),
            "provider-b": BrowserProvider("provider-b"),
        },
        acquisition=StaticAcquisitionModules(
            releases=ReleaseSelectionService(
                provider=BrowserReleaseProvider(), cache=ReleaseSelectionCache()
            ),
            download_client=clients["qBittorrent"],
            release_id="prowlarr",
            download_id="qbittorrent",
        ),
    )
    app.state.browser_clients = clients

    @app.get("/test-assets/broken-poster")
    def broken_poster() -> Response:
        return Response(content=b"not-an-image", media_type="image/jpeg")

    sessions = session_factory(app.state.engine)
    with sessions() as session:
        item = MediaItem(provider_key="manual", external_id=str(uuid4()), kind="movie")
        session.add(item)
        session.flush()
        metadata = NormalizedMetadata(
            kind=MediaKind.MOVIE,
            titles={"en": "Pending Movie", "ru": "Ожидающий фильм"},
            year=2024,
            provenance=Provenance(provider_id="manual", external_id=item.external_id, locale="en"),
        )
        revision = CatalogService(session).add_revision(item, RevisionInput(normalized=metadata))
        pending = Acquisition(
            id=(pending_id := uuid4()),
            correlation=f"mf-acq-{pending_id}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="qbittorrent",
            download_client_module_version="9.8.7",
            media_item_id=item.id,
            metadata_revision_id=revision.id,
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


@pytest.fixture
def default_runtime_browser_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'default-browser.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long browser test secret")
    monkeypatch.setenv("TMDB_TOKEN", "tmdb")
    monkeypatch.setenv("PROWLARR_URL", "https://prowlarr.example.test")
    monkeypatch.setenv("PROWLARR_API_KEY", "prowlarr")
    monkeypatch.setenv("QBITTORRENT_URL", "https://qb.example.test")
    monkeypatch.setenv("QBITTORRENT_USERNAME", "user")
    monkeypatch.setenv("QBITTORRENT_PASSWORD", "password")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/configuration"):
            return httpx.Response(200, json={})
        if request.url.path == "/api/v1/system/status":
            return httpx.Response(200, json={"version": "1"})
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/categories":
            return httpx.Response(200, json={"movies": {"savePath": "/movies"}})
        return httpx.Response(404)

    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    rebuilt = create_application(
        environment={
            "MEDIA_FINDER_DATABASE_URL": database_url,
            "MEDIA_FINDER_UI_SECRET": "a sufficiently long browser test secret",
            "MEDIA_FINDER_INTEGRATION_TOKEN": "browser-integration-token",
            "MEDIA_FINDER_SECURE_COOKIE": "false",
            "MEDIA_FINDER_UI_MODE": "builtin",
            "TMDB_TOKEN": "tmdb",
            "PROWLARR_URL": "https://prowlarr.example.test",
            "PROWLARR_API_KEY": "prowlarr",
            "QBITTORRENT_URL": "https://qb.example.test",
            "QBITTORRENT_USERNAME": "user",
            "QBITTORRENT_PASSWORD": "password",
        },
        http_client_factory=factory,
    )
    port = _port()
    server = uvicorn.Server(uvicorn.Config(rebuilt, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("default runtime browser server did not start")
    yield BrowserSite(f"http://127.0.0.1:{port}", rebuilt, "")
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def unavailable_runtime_browser_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'unavailable-browser.db'}"
    migrate_to_head(database_url)
    environment = {
        "TMDB_TOKEN": "browser-tmdb-secret",
        "PROWLARR_URL": "https://prowlarr.example.test",
        "PROWLARR_API_KEY": "browser-prowlarr-secret",
        "QBITTORRENT_URL": "https://qb.example.test",
        "QBITTORRENT_USERNAME": "browser-qb-user",
        "QBITTORRENT_PASSWORD": "browser-qb-password",
    }
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long browser test secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json={})
        if request.url.host == "prowlarr.example.test":
            return httpx.Response(503, text="never-render-upstream-body")
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, json={})

    app = create_application(
        environment={
            "MEDIA_FINDER_DATABASE_URL": database_url,
            "MEDIA_FINDER_UI_SECRET": "a sufficiently long browser test secret",
            "MEDIA_FINDER_INTEGRATION_TOKEN": "browser-integration-token",
            "MEDIA_FINDER_SECURE_COOKIE": "false",
            "MEDIA_FINDER_UI_MODE": "builtin",
            **environment,
        },
        http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    app.state.test_environment_values = tuple(environment.values())
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("unavailable runtime browser server did not start")
    yield BrowserSite(f"http://127.0.0.1:{port}", app, "")
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def fake_gateway_browser_site():
    app = create_builtin_ui(
        gateway=FakeControlGateway(),
        security=FakeBrowserSecurity(),
    )
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("fake gateway browser server did not start")
    yield BrowserSite(f"http://127.0.0.1:{port}", app, "")
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def external_ui_browser_site():
    frontend = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    control = create_control_app(
        gateway=FakeControlGateway(),
        security=BackendBrowserSecurity(secret=b"external-ui-session-secret-at-least-32"),
    )

    @frontend.get("/", response_class=HTMLResponse)
    async def external_page() -> str:
        return """<!doctype html><html lang="en"><body><main id="state">starting</main>
        <script>
        (async () => {
          const session = await fetch('/api/control/v1/session').then(r => r.json());
          const headers = {'Content-Type': 'application/json',
                           'X-CSRF-Token': session.csrf_token};
          const catalog = await fetch('/api/control/v1/media-items').then(r => r.json());
          const search = await fetch('/api/control/v1/metadata-searches', {
            method: 'POST', headers, body: JSON.stringify({query: 'Example', locale: 'en'})
          }).then(r => r.json());
          await fetch('/api/control/v1/metadata-selections/' + search[0].token, {
            method: 'POST', headers, body: JSON.stringify({})
          });
          await fetch('/api/control/v1/manual-imports', {
            method: 'POST', headers, body: JSON.stringify({document: {
              schema_version: '1', kind: 'movie', locale: 'en',
              titles: {en: 'External Manual'}
            }})
          });
          const releases = await fetch('/api/control/v1/media-items/movie-1/release-searches', {
            method: 'POST', headers, body: JSON.stringify({query: 'Example'})
          }).then(r => r.json());
          const destinations = await fetch(
            '/api/control/v1/download-destinations'
          ).then(r => r.json());
          const acquisition = await fetch('/api/control/v1/acquisitions', {
            method: 'POST', headers, body: JSON.stringify({media_item_id: 'movie-1',
              release_token: releases[0].token, destination: destinations[0].key,
              idempotency_key: 'external-ui-attempt'})
          }).then(r => r.json());
          const reconciled = await fetch(
            '/api/control/v1/acquisitions/' + acquisition.id + '/reconcile',
            {method: 'POST', headers, body: JSON.stringify({})}
          ).then(r => r.json());
          document.querySelector('#state').textContent =
              catalog.items[0].title + '|' + reconciled.status;
        })().catch(error => document.querySelector('#state').textContent = 'error:' + error);
        </script></body></html>"""

    frontend.mount("/api/control", control)
    port = _port()
    server = uvicorn.Server(
        uvicorn.Config(frontend, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("external UI browser server did not start")
    yield BrowserSite(f"http://127.0.0.1:{port}", frontend, "")
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


def _axe(page: Page, site: BrowserSite, selector: str | None = None) -> None:
    page.add_script_tag(url=f"{site.url}/static/axe.min.js")
    serious = page.evaluate(
        """async (selector) => (await axe.run(
        selector ? document.querySelector(selector) : document,
        {resultTypes: ['violations']}
        )).violations
        .filter(v => ['serious', 'critical'].includes(v.impact))
        .map(v => ({id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target)}))""",
        selector,
    )
    assert serious == []


def _csrf(page: Page) -> str:
    return page.locator('input[name="csrf"]').first.get_attribute("value") or ""


def test_isolated_builtin_ui_browser_uses_only_fake_ports(
    browser: Browser,
    fake_gateway_browser_site: BrowserSite,
) -> None:
    page, failures = _strict_page(browser, locale="ru-RU")
    page.goto(fake_gateway_browser_site.url)
    assert page.get_by_text("Пример фильма").is_visible()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.classList.contains('skip-link')")
    _axe(page, fake_gateway_browser_site)
    page.get_by_role("link", name="Добавить тайтл").click()
    page.get_by_test_id("add-mode-manual").click()
    assert page.get_by_test_id("manual-structured-form").is_visible()
    _axe(page, fake_gateway_browser_site)
    assert failures == []
    page.context.close()


def test_minimal_same_origin_external_ui_uses_only_control_api(
    browser: Browser,
    external_ui_browser_site: BrowserSite,
) -> None:
    page, failures = _strict_page(browser)
    page.goto(external_ui_browser_site.url)
    page.locator("#state").filter(has_text="Example Movie|submitted").wait_for()
    assert failures == []
    assert page.evaluate(
        "performance.getEntriesByType('resource').every(r => !r.name.includes('/api/v1'))"
    )
    page.context.close()


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
    page.get_by_role("button", name="Add episode").focus()
    page.keyboard.press("Enter")
    assert page.get_by_label("Episode number").count() == 2
    page.get_by_role("button", name="Remove episode").last.focus()
    page.keyboard.press("Enter")
    assert page.get_by_label("Episode number").count() == 1
    page.get_by_role("button", name="Add season").focus()
    page.keyboard.press("Enter")
    page.get_by_label("Season number").last.fill("2")
    page.get_by_label("Episode number").last.fill("1")
    page.get_by_label("Episode title").last.fill("Second season pilot")
    page.get_by_role("button", name="Add season").focus()
    page.keyboard.press("Enter")
    assert page.get_by_label("Season number").count() == 3
    page.get_by_role("button", name="Remove season").last.focus()
    page.keyboard.press("Enter")
    assert page.get_by_label("Season number").count() == 2
    _axe(page, browser_site)
    page.get_by_role("button", name="Save Manual metadata").focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/items/**?saved=1")
    assert page.get_by_role("status").inner_text() == "Title saved."
    assert page.evaluate("document.activeElement.id") == "ui-feedback"
    assert page.get_by_text("Season 00").is_visible()
    assert page.get_by_text(re.compile("Pilot Special")).is_visible()
    assert page.get_by_text(re.compile("Second season pilot")).is_visible()

    page.get_by_role("link", name="Edit metadata").click()
    page.get_by_label("Title", exact=True).fill("Edited Keyboard Series")
    page.get_by_role("button", name="Save Manual metadata").click()
    assert page.get_by_test_id("manual-revision-confirmation").is_visible()
    draft_token = page.locator('input[name="draft_token"]').input_value()
    csrf = _csrf(page)
    page.get_by_role("button", name="Create revision").click()
    page.wait_for_url("**/items/**?saved=1")
    assert page.get_by_role("heading", name="Edited Keyboard Series").is_visible()
    expired = page.request.post(
        f"{browser_site.url}/ui/manual/confirm",
        form={"csrf": csrf, "draft_token": draft_token},
    )
    assert expired.status == 410
    assert 'data-error-code="manual_draft_expired"' in expired.text()
    assert "The Manual metadata draft expired." in expired.text()
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
        _axe(page, browser_site)

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
    _axe(page, browser_site, '[data-testid="similarity-warning"]')
    page.get_by_role("button", name="Add as a separate identity").click()
    page.wait_for_url("**/items/**?saved=1")
    _axe(page, browser_site)
    assert failures == []
    page.context.close()


def test_single_client_idempotent_submit_and_pending_reconcile(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(f"{browser_site.url}/items/{browser_site.pending_item_id}/releases")
    page.get_by_label("Free query").fill("Pending Movie")
    page.get_by_role("button", name="Search torrents").click()
    page.get_by_test_id("release-result").get_by_role("radio").check()
    page.get_by_test_id("destination-select").wait_for()
    assert page.get_by_test_id("destination-select").input_value() == "second"
    payload = {
        "csrf": _csrf(page),
        "release_token": page.get_by_test_id("release-result")
        .get_by_role("radio")
        .get_attribute("value"),
        "destination": "second",
        "idempotency_key": page.locator('input[name="idempotency_key"]').input_value(),
    }
    browser_site.app.state.browser_clients["qBittorrent"].destination = "current"
    page.get_by_test_id("submit-acquisition").click()
    page.get_by_role("alert").wait_for()
    assert page.get_by_role("alert").locator("code").inner_text() == (
        "download_destination_unavailable"
    )
    assert page.get_by_test_id("destination-select").input_value() == "current"
    _axe(page, browser_site, "#acquisition-form")
    assert len(failures) == 1 and "status of 409 (Conflict)" in failures[0]
    failures.clear()  # Expected semantic conflict rendered as a retryable form.
    page.get_by_role("button", name="Retry acquisition").click()
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
    assert checklist.locator('[data-environment-variable="PROWLARR_URL"]').is_visible()
    assert checklist.locator('[data-environment-variable="QBITTORRENT_URL"]').is_visible()
    assert page.locator('form[action^="/ui/settings/"]').count() == 0

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


def test_browser_observes_default_runtime_from_environment(
    browser: Browser, default_runtime_browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(f"{default_runtime_browser_site.url}/settings")
    checklist = page.get_by_test_id("readiness-checklist")
    assert checklist.locator(
        '[data-integration="tmdb"][data-integration-state="ready"]'
    ).is_visible()
    assert checklist.locator(
        '[data-integration="prowlarr"][data-integration-state="ready"]'
    ).is_visible()
    assert checklist.locator(
        '[data-integration="qbittorrent"][data-integration-state="ready"]'
    ).is_visible()
    _axe(page, default_runtime_browser_site)
    page.goto(f"{default_runtime_browser_site.url}/about")
    assert "User-provided metadata" in page.locator("main").inner_text()
    assert "This product uses the TMDB API" in page.locator("main").inner_text()
    _axe(page, default_runtime_browser_site)
    assert failures == []
    page.context.close()


def test_browser_shows_unavailable_without_values_and_rejects_legacy_routes(
    browser: Browser, unavailable_runtime_browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(f"{unavailable_runtime_browser_site.url}/settings")
    assert page.locator(
        '[data-integration="prowlarr"][data-integration-state="unavailable"]'
    ).is_visible()
    assert page.locator('[data-integration="tmdb"][data-integration-state="ready"]').is_visible()
    for value in unavailable_runtime_browser_site.app.state.test_environment_values:
        assert value not in page.locator("main").inner_text()
    legacy = page.request.post(
        f"{unavailable_runtime_browser_site.url}/ui/settings/prowlarr",
        form={},
        max_redirects=0,
    )
    assert legacy.status in {404, 405}
    page.get_by_test_id("locale-switcher").select_option("ru")
    page.wait_for_load_state("networkidle")
    prowlarr = page.locator('[data-integration="prowlarr"]')
    assert "Недоступно" in prowlarr.inner_text()
    _axe(page, unavailable_runtime_browser_site)
    assert failures == []
    page.context.close()


def test_metadata_locale_poster_placeholder_and_read_only_settings_browser(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser, locale="ru-RU")
    page.goto(f"{browser_site.url}/add/manual")
    assert page.get_by_test_id("locale-switcher").input_value() == "ru"
    assert page.get_by_test_id("metadata-locale-switcher").input_value() == "ru"
    assert page.get_by_label("Язык метаданных").last.input_value() == "ru"

    page.get_by_test_id("metadata-locale-switcher").select_option("en")
    page.wait_for_load_state("networkidle")
    page.get_by_test_id("locale-switcher").select_option("en")
    page.wait_for_load_state("networkidle")
    assert page.get_by_test_id("metadata-locale-switcher").input_value() == "en"
    assert page.get_by_label("Metadata locale").last.input_value() == "en"

    page.goto(browser_site.url)
    assert page.get_by_test_id("poster-placeholder").first.is_visible()
    page.goto(f"{browser_site.url}/settings")
    assert page.locator('form[action^="/ui/settings/"]').count() == 0
    assert page.locator('[data-environment-variable="QBITTORRENT_PASSWORD"]').is_visible()
    page.get_by_test_id("locale-switcher").select_option("ru")
    page.wait_for_load_state("networkidle")
    assert page.locator('[data-environment-variable="PROWLARR_URL"]').is_visible()
    _axe(page, browser_site)
    assert failures == []
    page.context.close()


def test_completed_broken_poster_is_removed_when_fallback_binding_runs(
    browser: Browser, browser_site: BrowserSite
) -> None:
    page, failures = _strict_page(browser)
    page.goto(browser_site.url)

    result = page.evaluate(
        """async (url) => {
          const frame = document.createElement('div');
          frame.className = 'poster-frame';
          frame.innerHTML = '<div class="poster-placeholder">MF</div>';
          const image = document.createElement('img');
          image.dataset.poster = '';
          frame.append(image);
          document.body.append(frame);
          image.src = url;
          await new Promise((resolve) => {
            if (image.complete) resolve();
            else {
              image.addEventListener('load', resolve, {once: true});
              image.addEventListener('error', resolve, {once: true});
            }
          });
          const failedBeforeBinding = image.complete && image.naturalWidth === 0;
          document.dispatchEvent(new CustomEvent('htmx:afterSwap', {
            detail: {target: frame}
          }));
          await new Promise((resolve) => requestAnimationFrame(resolve));
          return {
            failedBeforeBinding,
            remainingImages: frame.querySelectorAll('img[data-poster]').length,
            placeholderVisible:
              frame.querySelector('.poster-placeholder').getClientRects().length > 0
          };
        }""",
        f"{browser_site.url}/test-assets/broken-poster",
    )

    assert result == {
        "failedBeforeBinding": True,
        "remainingImages": 0,
        "placeholderVisible": True,
    }
    assert failures == []
    page.context.close()
