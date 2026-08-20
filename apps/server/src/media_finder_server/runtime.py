"""The single production composition and lifecycle owner."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime

import httpx
import uvicorn
from fastapi import FastAPI
from media_finder_builtin_ui import create_builtin_ui
from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_core.catalog import MetadataRetentionService
from media_finder_core.catalog.persistence import (
    SqlAlchemyCatalogQueries,
    SqlAlchemyCatalogUnitOfWork,
)
from media_finder_core.control import ManualDraft
from media_finder_core.platform import (
    CoreConfiguration,
    EphemeralCache,
    MaintenanceRunner,
    SqlAlchemyMaintenanceState,
    SystemClock,
    create_database,
    migrate_to_head,
    session_factory,
)
from media_finder_sdk import (
    MetadataProvider,
    MetadataRetentionPolicy,
    MetadataSearchResult,
    StaticModuleRegistry,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from .control_api import create_control_app
from .control_gateway import BackendControlGateway
from .control_security import BackendBrowserSecurity
from .modules import (
    create_runtime_module_composition,
)
from .processor_api import create_processor_app

MAINTENANCE_CHECK_SECONDS = 60 * 60
LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplicationResources:
    """One attempt-local graph shared by every production delivery adapter."""

    configuration: CoreConfiguration
    engine: Engine
    sessions: sessionmaker[Session]
    registry: StaticModuleRegistry
    module_runtime: ModuleRuntime
    release_selection_cache: ReleaseSelectionCache
    release_selections: ReleaseSelectionService
    metadata_selections: EphemeralCache[MetadataSearchResult]
    manual_drafts: EphemeralCache[ManualDraft]
    gateway: BackendControlGateway
    security: BackendBrowserSecurity
    maintenance_runner: MaintenanceRunner
    control_app: FastAPI
    processor_app: FastAPI
    ui_app: FastAPI | None


class _RetentionCoordinator:
    """Resolve currently available module capabilities for each generic cycle."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        module_runtime: ModuleRuntime,
        clock: SystemClock,
    ) -> None:
        self._sessions = sessions
        self._module_runtime = module_runtime
        self._clock = clock

    def run(self, now: datetime) -> object:
        del now
        policies: dict[str, MetadataRetentionPolicy] = {}
        providers: dict[str, MetadataProvider] = {}
        for module_id in self._module_runtime.registry.metadata:
            try:
                policies[module_id] = self._module_runtime.retention_policy(module_id)
            except Exception:
                continue
            try:
                providers[module_id] = self._module_runtime.metadata_provider(module_id)
            except Exception:
                continue
        return MetadataRetentionService(
            query_port=SqlAlchemyCatalogQueries(self._sessions),
            unit_of_work=SqlAlchemyCatalogUnitOfWork(self._sessions),
            policies=policies,
            providers=providers,
            clock=self._clock.now,
        ).run()


def core_configuration(
    environment: Mapping[str, str] | None = None,
) -> CoreConfiguration:
    return CoreConfiguration.from_environment(os.environ if environment is None else environment)


def database_url() -> str:
    return core_configuration().database_url


def ui_mode() -> str:
    return core_configuration().ui_mode


class _CleanupScope:
    """Best-effort reverse-order cleanup preserving the first actionable error."""

    def __init__(self) -> None:
        self._operations: list[Callable[[], None]] = []

    def own(self, operation: Callable[[], None]) -> None:
        self._operations.append(operation)

    def close(self) -> BaseException | None:
        first_error: BaseException | None = None
        for operation in reversed(self._operations):
            try:
                operation()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        self._operations.clear()
        return first_error


def _build_resources(
    *,
    environment: Mapping[str, str],
    configuration: CoreConfiguration,
    http_client_factory: Callable[[], httpx.Client],
    cleanup: _CleanupScope,
) -> ApplicationResources:
    engine = create_database(configuration.database_url)
    cleanup.own(lambda: engine.dispose())
    sessions = session_factory(engine)
    release_cache = ReleaseSelectionCache()
    composition = create_runtime_module_composition(
        environment=environment,
        client_factory=http_client_factory,
        release_cache=release_cache,
    )
    cleanup.own(lambda: composition.runtime.close())
    cleanup.own(lambda: composition.release_selections.close())
    metadata_selections: EphemeralCache[MetadataSearchResult] = EphemeralCache()
    cleanup.own(lambda: metadata_selections.clear())
    manual_drafts: EphemeralCache[ManualDraft] = EphemeralCache()
    cleanup.own(lambda: manual_drafts.clear())
    secret = configuration.ui_secret.get_secret_value().encode()
    gateway = BackendControlGateway(
        sessions=sessions,
        cursor_secret=secret,
        registry=composition.registry,
        module_runtime=composition.runtime,
        release_selections=composition.release_selections,
        release_manifest=composition.release_manifest,
        download_manifest=composition.download_manifest,
        environment=environment,
        attribution_notices=composition.attribution_notices,
        metadata_selections=metadata_selections,
        manual_drafts=manual_drafts,
    )
    security = BackendBrowserSecurity(secret=secret)
    clock = SystemClock()
    maintenance_runner = MaintenanceRunner(
        coordinator=_RetentionCoordinator(
            sessions=sessions,
            module_runtime=composition.runtime,
            clock=clock,
        ),
        state=SqlAlchemyMaintenanceState(sessions),
        clock=clock,
    )
    control_app = create_control_app(
        gateway=gateway,
        security=security,
        secure_cookie=configuration.secure_cookie,
    )
    retention_policies = {
        module_id: composition.runtime.retention_policy(module_id)
        for module_id in composition.registry.metadata
    }
    processor_app = create_processor_app(
        integration_token=configuration.integration_token.get_secret_value(),
        retention_policies=retention_policies,
        database_engine=engine,
        sessions=sessions,
    )
    ui_app = create_builtin_ui() if configuration.ui_mode == "builtin" else None
    return ApplicationResources(
        configuration=configuration,
        engine=engine,
        sessions=sessions,
        registry=composition.registry,
        module_runtime=composition.runtime,
        release_selection_cache=release_cache,
        release_selections=composition.release_selections,
        metadata_selections=metadata_selections,
        manual_drafts=manual_drafts,
        gateway=gateway,
        security=security,
        maintenance_runner=maintenance_runner,
        control_app=control_app,
        processor_app=processor_app,
        ui_app=ui_app,
    )


class _ControlDispatch:
    def __init__(self, application: FastAPI) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        resources = getattr(self._application.state, "resources", None)
        if resources is None:
            await Response(status_code=503)(scope, receive, send)
            return
        await resources.control_app(scope, receive, send)


class _RootDispatch:
    def __init__(self, application: FastAPI) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        resources = getattr(self._application.state, "resources", None)
        if resources is None:
            await Response(status_code=503)(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        selected = (
            resources.processor_app
            if path.startswith(("/api/v1", "/health")) or resources.ui_app is None
            else resources.ui_app
        )
        await selected(scope, receive, send)


def create_application(
    *,
    environment: Mapping[str, str] | None = None,
    http_client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> FastAPI:
    """Return an allocation-free shell whose lifespan owns one resource graph."""
    snapshot = dict(os.environ if environment is None else environment)
    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @asynccontextmanager
    async def root_lifespan(_: FastAPI) -> AsyncIterator[None]:
        cleanup = _CleanupScope()
        stop = asyncio.Event()
        maintenance: asyncio.Task[None] | None = None
        active_error: BaseException | None = None
        try:
            configuration = core_configuration(snapshot)
            resources = _build_resources(
                environment=snapshot,
                configuration=configuration,
                http_client_factory=http_client_factory,
                cleanup=cleanup,
            )
            _publish_resources(application, resources)
            maintenance = asyncio.create_task(_maintenance_loop(resources, stop))
            yield
        except BaseException as error:
            active_error = error
            raise
        finally:
            stop.set()
            shutdown_error: BaseException | None = None
            if maintenance is not None:
                try:
                    await maintenance
                except BaseException as error:
                    shutdown_error = error
            _unpublish_resources(application)
            cleanup_error = cleanup.close()
            if shutdown_error is None:
                shutdown_error = cleanup_error
            if active_error is None and shutdown_error is not None:
                raise shutdown_error

    application.router.lifespan_context = root_lifespan
    application.mount("/api/control", _ControlDispatch(application))
    application.mount("/", _RootDispatch(application))
    return application


def _publish_resources(application: FastAPI, resources: ApplicationResources) -> None:
    application.state.resources = resources
    application.state.engine = resources.engine
    application.state.sessions = resources.sessions
    application.state.gateway = resources.gateway
    application.state.maintenance_runner = resources.maintenance_runner
    application.state.processor = resources.processor_app


def _unpublish_resources(application: FastAPI) -> None:
    for name in (
        "resources",
        "engine",
        "sessions",
        "gateway",
        "maintenance_runner",
        "processor",
    ):
        application.state._state.pop(name, None)


def _execute_maintenance(resources: ApplicationResources, *, startup: bool) -> None:
    if startup:
        resources.maintenance_runner.run_at_startup()
    else:
        resources.maintenance_runner.run_if_daily_due()


async def _maintenance_loop(
    resources: ApplicationResources,
    stop: asyncio.Event,
) -> None:
    startup = True
    while not stop.is_set():
        try:
            await asyncio.to_thread(_execute_maintenance, resources, startup=startup)
        except Exception:
            logger.error("Generic metadata maintenance cycle failed")
        startup = False
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=MAINTENANCE_CHECK_SECONDS)


def configure_logging(log_level: str) -> None:
    """Apply one process-wide level to the root logger.

    Uvicorn's own loggers are levelled separately through the ``log_level``
    argument passed to ``uvicorn.run``; the root logger governs application
    loggers and any third-party loggers that propagate to it.
    """

    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    root = logging.getLogger()
    root.setLevel(numeric_level)
    if not root.hasHandlers():
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)


def run() -> None:
    """Migrate before constructing and serving one worker."""

    configuration = core_configuration()
    configure_logging(configuration.log_level)
    migrate_to_head(configuration.database_url)
    application = create_application()
    uvicorn.run(
        application,
        host="0.0.0.0",
        port=8000,
        workers=1,
        proxy_headers=True,
        log_level=configuration.log_level,
    )


__all__ = [
    "ApplicationResources",
    "core_configuration",
    "create_application",
    "database_url",
    "run",
    "ui_mode",
]
