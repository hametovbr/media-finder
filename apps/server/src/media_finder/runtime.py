"""Production process composition and migration-gated startup."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from media_finder_builtin_ui import BuiltinUIOptions, create_builtin_ui
from media_finder_core.catalog import MetadataRetentionService
from media_finder_core.catalog.persistence import (
    SqlAlchemyCatalogQueries,
    SqlAlchemyCatalogUnitOfWork,
)
from media_finder_core.platform import (
    CoreConfiguration,
    MaintenanceRunner,
    SqlAlchemyMaintenanceState,
    SystemClock,
    create_database,
    migrate_to_head,
    session_factory,
)
from media_finder_sdk import MetadataProvider as CoreMetadataProvider
from media_finder_sdk import MetadataRetentionPolicy
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .api import create_app as create_processor_app
from .control_api import create_control_app
from .control_gateway import BackendControlGateway
from .control_security import BackendBrowserSecurity
from .integration_runtime import (
    DefaultRuntimeFactory,
    RuntimeResolver,
)
from .sdk.registration import StaticModuleRegistry

MAINTENANCE_CHECK_SECONDS = 60 * 60
logger = logging.getLogger(__name__)


def core_configuration(
    environment: Mapping[str, str] | None = None,
) -> CoreConfiguration:
    return CoreConfiguration.from_environment(os.environ if environment is None else environment)


def database_url() -> str:
    return core_configuration().database_url


def ui_mode() -> str:
    return core_configuration().ui_mode


def create_application(
    *,
    registry: StaticModuleRegistry,
    runtime_factory: DefaultRuntimeFactory,
    configuration: CoreConfiguration | None = None,
) -> FastAPI:
    """Compose browser and processor interfaces from environment configuration."""

    selected = configuration or core_configuration()
    url = selected.database_url
    engine = create_database(url)
    sessions = session_factory(engine)
    try:
        return _compose_application(
            url=url,
            configuration=selected,
            engine=engine,
            sessions=sessions,
            registry=registry,
            runtime_factory=runtime_factory,
        )
    except BaseException:
        engine.dispose()
        raise


def _compose_application(
    *,
    url: str,
    configuration: CoreConfiguration,
    engine: Engine,
    sessions: sessionmaker[Session],
    registry: StaticModuleRegistry,
    runtime_factory: DefaultRuntimeFactory,
) -> FastAPI:
    secret = configuration.ui_secret.get_secret_value()
    secret_bytes = secret.encode()
    runtime = RuntimeResolver(
        factory=runtime_factory,
        providers=registry.retention_providers(),
    )
    gateway = BackendControlGateway(
        sessions=sessions,
        cursor_secret=secret_bytes,
        runtime=runtime,
        registry=registry,
        metadata_capabilities=runtime_factory.module_runtime,
    )
    security = BackendBrowserSecurity(secret=secret_bytes)
    application = (
        create_builtin_ui(
            gateway=gateway,
            security=security,
            options=BuiltinUIOptions(secure_cookie=configuration.secure_cookie),
        )
        if configuration.ui_mode == "builtin"
        else FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    )
    control = create_control_app(
        gateway=gateway,
        security=security,
        secure_cookie=configuration.secure_cookie,
    )
    module_runtime = runtime_factory.module_runtime
    if module_runtime is None:
        raise RuntimeError("metadata_module_runtime_unavailable")
    retention_policies = {
        module_id: module_runtime.retention_policy(module_id)
        for module_id in module_runtime.registry.metadata
    }
    processor = create_processor_app(
        url,
        integration_token=configuration.integration_token.get_secret_value(),
        retention_policies=retention_policies,
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
            try:
                await maintenance
            finally:
                try:
                    runtime_factory.close()
                finally:
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
    module_runtime = application.state.runtime_factory.module_runtime
    if module_runtime is None:
        raise RuntimeError("metadata_module_runtime_unavailable")
    policies: dict[str, MetadataRetentionPolicy] = {}
    providers: dict[str, CoreMetadataProvider] = {}
    for module_id in module_runtime.registry.metadata:
        try:
            policies[module_id] = module_runtime.retention_policy(module_id)
        except Exception:
            continue
        try:
            providers[module_id] = module_runtime.metadata_provider(module_id)
        except Exception:
            continue
    clock = SystemClock()
    service = MetadataRetentionService(
        query_port=SqlAlchemyCatalogQueries(application.state.sessions),
        unit_of_work=SqlAlchemyCatalogUnitOfWork(application.state.sessions),
        policies=policies,
        providers=providers,
        clock=clock.now,
    )
    runner = MaintenanceRunner(
        coordinator=_CoreRetentionCoordinator(service),
        state=SqlAlchemyMaintenanceState(application.state.sessions),
        clock=clock,
    )
    if startup:
        runner.run_at_startup()
    else:
        runner.run_if_daily_due()


class _CoreRetentionCoordinator:
    def __init__(self, service: MetadataRetentionService) -> None:
        self._service = service

    def run(self, now: datetime) -> None:
        del now
        self._service.run()


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


def run(
    *,
    registry: StaticModuleRegistry,
    runtime_factory: DefaultRuntimeFactory,
    configuration: CoreConfiguration | None = None,
) -> None:
    """Migrate storage before constructing or starting the single web worker."""

    selected = configuration or core_configuration()
    migrate_to_head(selected.database_url)
    application = create_application(
        registry=registry,
        runtime_factory=runtime_factory,
        configuration=selected,
    )
    uvicorn.run(
        application,
        host="0.0.0.0",
        port=8000,
        workers=1,
        proxy_headers=True,
    )
