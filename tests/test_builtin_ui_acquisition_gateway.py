import re

from fastapi.testclient import TestClient
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_release_acquisition_diagnostics_and_about_use_fake_gateway() -> None:
    with TestClient(
        create_builtin_ui(
            gateway=FakeControlGateway(),
            security=FakeBrowserSecurity(),
        )
    ) as client:
        release = client.get("/items/movie-1/releases")
        csrf = _csrf(release.text)
        assert release.status_code == 200
        results = client.post(
            "/ui/items/movie-1/releases/search",
            data={"csrf": csrf, "query": "Example"},
        )
        assert results.status_code == 200
        assert "Example.Release.1080p" in results.text
        destinations = client.post(
            "/ui/qbittorrent/destinations",
            data={"csrf": csrf},
        )
        assert destinations.status_code == 200
        assert "Movies" in destinations.text

        submitted = client.post(
            "/ui/items/movie-1/acquisitions",
            data={
                "csrf": csrf,
                "release_token": "release-pending",
                "destination": "movies",
                "idempotency_key": "ui-attempt-1",
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303
        assert "acquisition=pending" in submitted.headers["location"]
        reconciled = client.post(
            "/ui/acquisitions/movie-1-acquisition/reconcile",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert reconciled.status_code == 303
        assert "reconciled=submitted" in reconciled.headers["location"]

        settings = client.get("/settings")
        assert settings.status_code == 200
        assert "MEDIA_FINDER_TMDB_API_TOKEN" in settings.text
        assert "secret-value" not in settings.text
        about = client.get("/about")
        assert about.status_code == 200
        assert "User-provided metadata" in about.text
