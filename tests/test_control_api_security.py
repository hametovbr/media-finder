from fake_control_gateway import FakeControlGateway
from fastapi.testclient import TestClient
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity


def _client(
    *, secure_cookie: bool = False, gateway: FakeControlGateway | None = None
) -> TestClient:
    return TestClient(
        create_control_app(
            gateway=gateway or FakeControlGateway(),
            security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
            secure_cookie=secure_cookie,
        ),
        base_url="https://testserver" if secure_cookie else "http://testserver",
    )


def test_session_bootstrap_and_reusable_csrf_preserve_cookie_contract() -> None:
    with _client(secure_cookie=True) as client:
        bootstrap = client.get("/v1/session", headers={"accept-language": "ru-RU"})
        assert bootstrap.status_code == 200
        assert bootstrap.json()["ui_locale"] == "ru"
        assert bootstrap.json()["metadata_locale"] == "ru"
        csrf = bootstrap.json()["csrf_token"]
        cookie = bootstrap.headers["set-cookie"]
        assert "mf_session=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Secure" in cookie
        assert "Path=/" in cookie

        headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
        first = client.patch("/v1/session", json={"metadata_locale": "en"}, headers=headers)
        second = client.patch("/v1/session", json={"ui_locale": "en"}, headers=headers)
        assert first.status_code == second.status_code == 200
        assert second.json()["ui_locale"] == "en"
        assert second.json()["metadata_locale"] == "en"
        assert second.json()["csrf_token"] == csrf


def test_control_mutations_require_json_valid_session_csrf_and_same_origin() -> None:
    with _client() as client:
        csrf = client.get("/v1/session").json()["csrf_token"]
        valid = {"Origin": "http://testserver", "X-CSRF-Token": csrf}

        cases = (
            ({"Origin": "http://testserver"}, "csrf_invalid"),
            (
                {"Origin": "https://attacker.example", "X-CSRF-Token": csrf},
                "origin_invalid",
            ),
        )
        for headers, code in cases:
            response = client.patch("/v1/session", json={"ui_locale": "en"}, headers=headers)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == code
            assert response.json()["error"]["request_id"]
            assert "access-control-allow-origin" not in response.headers

        wrong_type = client.patch(
            "/v1/session",
            content="ui_locale=en",
            headers=valid | {"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert wrong_type.status_code == 415
        assert wrong_type.json()["error"]["code"] == "json_required"

        client.cookies.set("mf_session", "invalid")
        invalid_session = client.patch("/v1/session", json={"ui_locale": "en"}, headers=valid)
        assert invalid_session.status_code == 403
        assert invalid_session.json()["error"]["code"] == "session_invalid"


def test_metadata_search_rejections_do_not_invoke_gateway_or_create_selection_state() -> None:
    class CountingGateway(FakeControlGateway):
        def __init__(self) -> None:
            super().__init__()
            self.search_calls = 0
            self.selection_tokens: set[str] = set()

        async def search_metadata(self, *, request):  # type: ignore[no-untyped-def]
            self.search_calls += 1
            results = await super().search_metadata(request=request)
            self.selection_tokens.update(result.token for result in results)
            return results

    gateway = CountingGateway()
    with _client(gateway=gateway) as client:
        csrf = client.get("/v1/session").json()["csrf_token"]
        valid = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
        payload = {"query": "Example", "locale": "en"}

        wrong_type = client.post(
            "/v1/metadata-searches",
            content="query=Example",
            headers=valid | {"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert wrong_type.status_code == 415

        for headers, code in (
            ({"Origin": "http://testserver"}, "csrf_invalid"),
            ({"Origin": "http://testserver", "X-CSRF-Token": "invalid"}, "csrf_invalid"),
            ({"Origin": "https://attacker.example", "X-CSRF-Token": csrf}, "origin_invalid"),
        ):
            rejected = client.post("/v1/metadata-searches", json=payload, headers=headers)
            assert rejected.status_code == 403
            assert rejected.json()["error"]["code"] == code

        client.cookies.clear()
        missing_session = client.post("/v1/metadata-searches", json=payload, headers=valid)
        assert missing_session.status_code == 403
        assert missing_session.json()["error"]["code"] == "session_invalid"

        refreshed_csrf = client.get("/v1/session").json()["csrf_token"]
        client.cookies.set("mf_session", "invalid")
        invalid_session = client.post(
            "/v1/metadata-searches",
            json=payload,
            headers={"Origin": "http://testserver", "X-CSRF-Token": refreshed_csrf},
        )
        assert invalid_session.status_code == 403
        assert invalid_session.json()["error"]["code"] == "session_invalid"

        assert gateway.search_calls == 0
        assert gateway.selection_tokens == set()


def test_control_body_is_bounded_and_framework_errors_are_safe() -> None:
    with _client() as client:
        csrf = client.get("/v1/session").json()["csrf_token"]
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        }
        oversized = client.patch(
            "/v1/session",
            content=b"{" + b'"padding":"' + (b"x" * 1_048_576) + b'"}',
            headers=headers,
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "request_body_too_large"

        invalid = client.patch("/v1/session", json={"ui_locale": "fr"}, headers=headers)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "request_invalid"
        assert "fr" not in str(invalid.json())

        missing = client.get("/v1/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        assert missing.headers["x-request-id"] == missing.json()["error"]["request_id"]
