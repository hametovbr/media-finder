"""Production process composition and migration-gated startup."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI

from .api import create_app as create_processor_app
from .db import migrate_to_head
from .maintenance import MaintenanceCoordinator, MaintenanceRunner
from .modules.registry import FIRST_PARTY_MODULES
from .sdk.protocols import MetadataProvider
from .ui import create_ui_app

DEFAULT_DATABASE_URL = "sqlite:////data/media-finder.db"
UI_SECRET_REFERENCE = "env:MEDIA_FINDER_UI_SECRET"
INTEGRATION_TOKEN_REFERENCE = "env:MEDIA_FINDER_INTEGRATION_TOKEN"
MAINTENANCE_CHECK_SECONDS = 60 * 60
logger = logging.getLogger(__name__)


def _secure_cookie() -> bool:
    value = os.environ.get("MEDIA_FINDER_SECURE_COOKIE", "true").casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("MEDIA_FINDER_SECURE_COOKIE must be a boolean")


def database_url() -> str:
    return os.environ.get("MEDIA_FINDER_DATABASE_URL", DEFAULT_DATABASE_URL)


def create_application() -> FastAPI:
    """Compose browser and processor interfaces from environment configuration."""

    url = database_url()
    ui = create_ui_app(
        url,
        session_secret_reference=UI_SECRET_REFERENCE,
        secure_cookie=_secure_cookie(),
    )
    providers: dict[str, MetadataProvider] = FIRST_PARTY_MODULES.retention_providers()
    processor = create_processor_app(
        url,
        integration_token_reference=INTEGRATION_TOKEN_REFERENCE,
        providers=providers,
    )
    ui_lifespan = ui.router.lifespan_context
    processor_lifespan = processor.router.lifespan_context

    @asynccontextmanager
    async def runtime_lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with ui_lifespan(ui), processor_lifespan(processor):
            maintenance = asyncio.create_task(_maintenance_loop(ui))
            try:
                yield
            finally:
                maintenance.cancel()
                with suppress(asyncio.CancelledError):
                    await maintenance

    ui.router.lifespan_context = runtime_lifespan
    ui.mount("/", processor)
    return ui


def _execute_maintenance(application: FastAPI, *, startup: bool) -> None:
    runtime = application.state.runtime
    providers = dict(runtime.supported_providers)
    providers.update(runtime.metadata_providers())
    runner = MaintenanceRunner(MaintenanceCoordinator(providers))
    with application.state.sessions() as session:
        now = datetime.now(UTC)
        if startup:
            runner.run_at_startup(session, now)
        else:
            runner.run_if_daily_due(session, now)


async def _maintenance_loop(application: FastAPI) -> None:
    startup = True
    while True:
        try:
            await asyncio.to_thread(_execute_maintenance, application, startup=startup)
        except Exception:
            logger.error("Generic metadata maintenance cycle failed")
        startup = False
        await asyncio.sleep(MAINTENANCE_CHECK_SECONDS)


def run() -> None:
    """Migrate storage before constructing or starting the single web worker."""

    migrate_to_head(database_url())
    application = create_application()
    uvicorn.run(
        application,
        host="0.0.0.0",
        port=8000,
        workers=1,
        proxy_headers=True,
    )


if __name__ == "__main__":
    run()
