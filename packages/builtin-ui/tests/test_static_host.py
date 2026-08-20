import asyncio
from pathlib import Path
from typing import Any

from media_finder_builtin_ui import create_builtin_ui

STATIC = Path(__file__).parents[1] / "src" / "media_finder_builtin_ui" / "static"


def _request(method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    async def invoke() -> tuple[int, dict[str, str], bytes]:
        messages: list[dict[str, Any]] = []
        request_available = True

        async def receive() -> dict[str, Any]:
            nonlocal request_available
            if request_available:
                request_available = False
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }
        await create_builtin_ui()(scope, receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        headers = {key.decode(): value.decode() for key, value in start["headers"]}
        return start["status"], headers, body

    return asyncio.run(invoke())


def test_index_and_supported_bookmarks_use_the_spa_entrypoint() -> None:
    for path in ("/", "/add", "/items/item-1", "/items/item-1/releases"):
        status, headers, body = _request("GET", path)
        assert status == 200
        assert b'<div id="root"></div>' in body
        assert headers["cache-control"] == "no-cache"

    assert _request("HEAD", "/items/item-1")[0] == 200


def test_hashed_assets_are_immutable_and_missing_assets_do_not_fall_back() -> None:
    asset = next((STATIC / "assets").glob("index-*.js"))

    status, headers, _ = _request("GET", f"/assets/{asset.name}")
    assert status == 200
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert _request("GET", "/assets/missing.js")[0] == 404


def test_mutations_never_use_the_spa_fallback() -> None:
    assert _request("POST", "/add")[0] in {404, 405}
    assert _request("POST", "/items/item-1/releases")[0] in {404, 405}
