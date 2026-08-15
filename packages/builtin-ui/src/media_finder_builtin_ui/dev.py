"""Development entry point for the isolated built-in interface."""

import uvicorn
from fastapi import FastAPI

from .app import create_builtin_ui
from .fake import FakeBrowserSecurity, FakeControlGateway


def create_dev_app(gateway: FakeControlGateway | None = None) -> FastAPI:
    return create_builtin_ui(
        gateway=gateway or FakeControlGateway(),
        security=FakeBrowserSecurity(),
    )


def main() -> None:
    uvicorn.run(create_dev_app(), host="127.0.0.1", port=8001)
