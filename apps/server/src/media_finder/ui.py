"""Compatibility composition for embedders of the built-in UI."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from media_finder_builtin_ui import BuiltinUIOptions, create_builtin_ui
from media_finder_builtin_ui.i18n import message_for
from media_finder_core.platform import create_database, session_factory
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .control_gateway import BackendControlGateway
from .control_security import BackendBrowserSecurity
from .integration_runtime import (
    AcquisitionModuleAccess,
    DefaultRuntimeFactory,
    RuntimeFactory,
    RuntimeResolver,
)
from .sdk.protocols import MetadataProvider
from .sdk.registration import StaticModuleRegistry

__all__ = ["create_ui_app", "error_message", "resolve_locale"]


def resolve_locale(override: str | None, accept_language: str | None) -> str:
    if override in {"en", "ru"}:
        return override
    for choice in (accept_language or "").split(","):
        language = choice.split(";", 1)[0].strip().split("-", 1)[0].casefold()
        if language in {"en", "ru"}:
            return language
    return "en"


def error_message(code: str, locale: str) -> tuple[str, str]:
    return message_for(code, resolve_locale(locale, None)), code


def create_ui_app(
    database_url: str,
    *,
    session_secret: str,
    secure_cookie: bool = False,
    providers: dict[str, MetadataProvider] | None = None,
    acquisition: AcquisitionModuleAccess | None = None,
    runtime_factory: RuntimeFactory | None = None,
    registry: StaticModuleRegistry,
    http_client_factory: Callable[[], httpx.Client] = httpx.Client,
    environment: Mapping[str, str] | None = None,
    **_: Any,
) -> FastAPI:
    """Build the port-only UI over explicitly composed backend resources."""

    engine = create_database(database_url)
    sessions = session_factory(engine)
    try:
        return _compose_ui_app(
            database_url=database_url,
            engine=engine,
            sessions=sessions,
            session_secret=session_secret,
            secure_cookie=secure_cookie,
            providers=providers,
            acquisition=acquisition,
            runtime_factory=runtime_factory,
            registry=registry,
            http_client_factory=http_client_factory,
            environment=environment,
        )
    except BaseException:
        engine.dispose()
        raise


def _compose_ui_app(
    *,
    database_url: str,
    engine: Engine,
    sessions: sessionmaker[Session],
    session_secret: str,
    secure_cookie: bool,
    providers: dict[str, MetadataProvider] | None,
    acquisition: AcquisitionModuleAccess | None,
    runtime_factory: RuntimeFactory | None,
    registry: StaticModuleRegistry,
    http_client_factory: Callable[[], httpx.Client],
    environment: Mapping[str, str] | None,
) -> FastAPI:
    secret = session_secret.encode()
    selected_factory = runtime_factory
    provider_registry = dict(providers or registry.retention_providers())
    if selected_factory is None and providers is None and acquisition is None:
        selected_factory = DefaultRuntimeFactory(
            environment=environment,
            http_client_factory=http_client_factory,
            registry=registry,
        )
    runtime = RuntimeResolver(
        factory=selected_factory,
        providers=provider_registry,
        acquisition=acquisition,
    )
    gateway = BackendControlGateway(
        sessions=sessions,
        cursor_secret=secret,
        runtime=runtime,
        registry=registry,
        metadata_capabilities=(
            selected_factory.module_runtime
            if isinstance(selected_factory, DefaultRuntimeFactory)
            else None
        ),
    )
    app = create_builtin_ui(
        gateway=gateway,
        security=BackendBrowserSecurity(secret=secret),
        options=BuiltinUIOptions(secure_cookie=secure_cookie),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            close = getattr(selected_factory, "close", None)
            try:
                if callable(close):
                    close()
            finally:
                engine.dispose()

    app.router.lifespan_context = lifespan
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.runtime = runtime
    app.state.gateway = gateway
    return app
