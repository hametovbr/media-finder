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
from media_finder_builtin_ui import BuiltinUIOptions, create_builtin_ui

from .api import create_app as create_processor_app
from .config import EnvReference, resolve_env_reference
from .control_api import create_control_app
from .control_gateway import BackendControlGateway
from .control_security import BackendBrowserSecurity
from .db import create_database, migrate_to_head, session_factory
from .integration_runtime import DefaultRuntimeFactory, RuntimeResolver
from .maintenance import MaintenanceCoordinator, MaintenanceRunner
from .modules.registry import FIRST_PARTY_MODULES
from .sdk.protocols import MetadataProvider
from .system_clients import ensure_system_qbittorrent

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


def ui_mode() -> str:
    value = os.environ.get("MEDIA_FINDER_UI_MODE", "builtin")
    if value not in {"builtin", "disabled"}:
        raise ValueError("MEDIA_FINDER_UI_MODE must be builtin or disabled")
    return value


def create_application() -> FastAPI:
    """Compose browser and processor interfaces from environment configuration."""

    url = database_url()
    mode = ui_mode()
    engine = create_database(url)
    sessions = session_factory(engine)
    with sessions() as database:
        ensure_system_qbittorrent(database)
    secret = resolve_env_reference(EnvReference(value=UI_SECRET_REFERENCE)).get_secret_value()
    secret_bytes = secret.encode()
    runtime_factory = DefaultRuntimeFactory()
    runtime = RuntimeResolver(
        factory=runtime_factory,
        providers=FIRST_PARTY_MODULES.retention_providers(),
        prowlarr=None,
        client_loader=None,
    )
    gateway = BackendControlGateway(
        sessions=sessions,
        cursor_secret=secret_bytes,
        runtime=runtime,
    )
    security = BackendBrowserSecurity(secret=secret_bytes)
    application = (
        create_builtin_ui(
            gateway=gateway,
            security=security,
            options=BuiltinUIOptions(secure_cookie=_secure_cookie()),
        )
        if mode == "builtin"
        else FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    )
    control = create_control_app(
        gateway=gateway,
        security=security,
        secure_cookie=_secure_cookie(),
    )
    providers: dict[str, MetadataProvider] = FIRST_PARTY_MODULES.retention_providers()
    processor = create_processor_app(
        url,
        integration_token_reference=INTEGRATION_TOKEN_REFERENCE,
        providers=providers,
        database_engine=engine,
        sessions=sessions,
    )

    @asynccontextmanager
    async def runtime_lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop_maintenance = asyncio.Event()
        maintenance = asyncio.create_task(_maintenance_loop(application, stop_maintenance))
        try:
            yield
        finally:
            stop_maintenance.set()
            await maintenance
            runtime_factory.close()
            engine.dispose()

    application.router.lifespan_context = runtime_lifespan
    application.state.engine = engine
    application.state.sessions = sessions
    application.state.runtime = runtime
    application.state.runtime_factory = runtime_factory
    application.state.gateway = gateway
    application.state.processor = processor
    application.mount("/api/control", control)
    application.mount("/", processor)
    return application


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


async def _maintenance_loop(application: FastAPI, stop: asyncio.Event) -> None:
    startup = True
    while not stop.is_set():
        try:
            await asyncio.to_thread(_execute_maintenance, application, startup=startup)
        except Exception:
            logger.error("Generic metadata maintenance cycle failed")
        startup = False
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=MAINTENANCE_CHECK_SECONDS)


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
