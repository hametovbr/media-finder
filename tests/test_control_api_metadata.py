from fake_control_gateway import FakeControlGateway
from fastapi.testclient import TestClient
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity


def _manual_document(external_id: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "1",
        "external_id": external_id,
        "kind": "series",
        "locale": "en",
        "titles": {"en": "Manual Series"},
        "seasons": [
            {
                "number": 0,
                "episodes": [{"number": 1, "title": "Special"}],
            }
        ],
    }


def test_metadata_and_manual_http_adapter_preserves_gateway_workflows() -> None:
    with TestClient(
        create_control_app(
            gateway=FakeControlGateway(),
            security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
        )
    ) as client:
        session = client.get("/v1/session").json()
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": session["csrf_token"],
        }
        providers = client.get("/v1/metadata-providers")
        assert providers.status_code == 200
        assert {value["key"] for value in providers.json()} == {"manual", "tmdb"}

        search = client.post(
            "/v1/metadata-searches",
            json={"query": "new", "locale": "en", "provider_keys": []},
            headers=headers,
        )
        assert search.status_code == 200
        assert search.json()[0] == {
            "token": "metadata-1",
            "provider_key": "tmdb",
            "external_id": "100",
            "kind": "series",
            "title": "Example Series",
            "year": 2025,
            "locale": "en",
            "description": "A fixture series description.",
            "poster_url": "https://images.example.test/posters/series-100.jpg",
        }
        assert "raw" not in search.text.casefold()

        absent = client.post(
            "/v1/metadata-searches",
            json={"query": "no preview", "locale": "en", "provider_keys": []},
            headers=headers,
        )
        assert absent.status_code == 200
        assert absent.json()[0]["description"] is None
        assert absent.json()[0]["poster_url"] is None
        selected = client.post(
            "/v1/metadata-selections/metadata-1",
            json={"confirm_similarity": False},
            headers=headers,
        )
        assert selected.status_code == 201
        assert selected.json()["provider_key"] == "tmdb"

        created = client.post(
            "/v1/manual-imports",
            json={"document": _manual_document()},
            headers=headers,
        )
        assert created.status_code == 201
        existing = client.post(
            "/v1/manual-imports",
            json={"document": _manual_document("e0a465bb-34eb-4565-bde2-b80d6e789b7c")},
            headers=headers,
        )
        assert existing.status_code == 409
        assert existing.json()["error"]["code"] == "confirmation_required"
        token = existing.json()["error"]["details"]["confirmation_token"]
        confirmed = client.post(f"/v1/manual-imports/{token}/confirm", json={}, headers=headers)
        assert confirmed.status_code == 200

        edited = client.put(
            "/v1/media-items/movie-1/manual-metadata",
            json=_manual_document("e0a465bb-34eb-4565-bde2-b80d6e789b7c"),
            headers=headers,
        )
        assert edited.status_code == 409
        edit_token = edited.json()["error"]["details"]["confirmation_token"]
        assert (
            client.post(
                f"/v1/manual-imports/{edit_token}/confirm", json={}, headers=headers
            ).status_code
            == 200
        )

        csv = client.post(
            "/v1/media-items/series-1/episode-imports",
            json={"csv": "season,episode,title\n1,1,Pilot\n"},
            headers=headers,
        )
        assert csv.status_code == 200

        duplicate_search = client.post(
            "/v1/metadata-searches",
            json={"query": "duplicate", "locale": "en"},
            headers=headers,
        ).json()[0]
        duplicate = client.post(
            f"/v1/metadata-selections/{duplicate_search['token']}",
            json={},
            headers=headers,
        )
        assert duplicate.status_code == 200

        similarity_search = client.post(
            "/v1/metadata-searches",
            json={"query": "similar", "locale": "en"},
            headers=headers,
        ).json()[0]
        similarity = client.post(
            f"/v1/metadata-selections/{similarity_search['token']}",
            json={},
            headers=headers,
        )
        assert similarity.status_code == 409
        assert similarity.json()["error"]["code"] == "confirmation_required"

        expired = client.post(
            "/v1/metadata-selections/metadata-expired",
            json={},
            headers=headers,
        )
        assert expired.status_code == 410
        assert expired.json()["error"]["code"] == "selection_expired"
