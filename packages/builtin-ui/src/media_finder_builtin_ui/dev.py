"""Development entry point for the isolated built-in interface."""

from html import escape

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from media_finder_control import Locale, PageRequest

from .fake import FakeControlGateway


def create_dev_app(gateway: FakeControlGateway | None = None) -> FastAPI:
    control = gateway or FakeControlGateway()
    app = FastAPI(title="Media Finder built-in UI development host")

    @app.get("/", response_class=HTMLResponse)
    async def catalog(locale: Locale = Locale.EN) -> str:
        page = await control.list_media_items(
            locale=locale,
            page=PageRequest(),
            collection_id=None,
            uncategorized=False,
            archived=False,
        )
        cards = "".join(f"<li>{escape(item.title)}</li>" for item in page.items)
        return f'<!doctype html><html lang="{locale.value}"><body><ul>{cards}</ul></body></html>'

    return app


def main() -> None:
    uvicorn.run(create_dev_app(), host="127.0.0.1", port=8001)
