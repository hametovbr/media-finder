"""Static host for the bundled browser interface."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

PACKAGE_ROOT = Path(__file__).parent
STATIC_ROOT = PACKAGE_ROOT / "static"
ASSET_ROOT = STATIC_ROOT / "assets"
INDEX = STATIC_ROOT / "index.html"


def _asset(asset_path: str) -> tuple[bytes, str]:
    candidate = (ASSET_ROOT / asset_path).resolve()
    if ASSET_ROOT.resolve() not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404)
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return candidate.read_bytes(), media_type


def create_builtin_ui() -> FastAPI:
    """Create a presentation-only ASGI application for packaged SPA assets."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    index = INDEX.read_bytes() if INDEX.is_file() else None

    @app.api_route("/assets/{asset_path:path}", methods=["GET", "HEAD"])
    async def static_asset(asset_path: str) -> Response:
        content, media_type = _asset(asset_path)
        return Response(
            content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.api_route("/{client_path:path}", methods=["GET", "HEAD"])
    async def spa_entrypoint(client_path: str) -> Response:
        if client_path.startswith(("api/", "health")) or index is None:
            raise HTTPException(status_code=404)
        return Response(
            index,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    return app
