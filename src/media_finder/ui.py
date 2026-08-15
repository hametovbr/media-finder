"""Compatibility composition for embedders of the built-in UI."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from media_finder_builtin_ui import BuiltinUIOptions, create_builtin_ui
from media_finder_builtin_ui.i18n import message_for

from .acquisition import ClientLoader
from .config import EnvReference, resolve_env_reference
from .control_gateway import BackendControlGateway
from .control_security import BackendBrowserSecurity
from .db import create_database, session_factory
from .integration_runtime import DefaultRuntimeFactory, RuntimeFactory, RuntimeResolver
from .modules.registry import FIRST_PARTY_MODULES
from .release_selection import ReleaseSelectionService
from .sdk.protocols import MetadataProvider
from .system_clients import ensure_system_qbittorrent

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
    session_secret_reference: str,
    secure_cookie: bool = False,
    providers: dict[str, MetadataProvider] | None = None,
    prowlarr: ReleaseSelectionService | None = None,
    client_loader: ClientLoader | None = None,
    runtime_factory: RuntimeFactory | None = None,
    http_client_factory: Callable[[], httpx.Client] = httpx.Client,
    environment: Mapping[str, str] | None = None,
    **_: Any,
) -> FastAPI:
    """Build the port-only UI over explicitly composed backend resources."""

    engine = create_database(database_url)
    sessions = session_factory(engine)
    with sessions() as database:
        ensure_system_qbittorrent(database)
    secret = (
        resolve_env_reference(EnvReference(value=session_secret_reference))
        .get_secret_value()
        .encode()
    )
    selected_factory = runtime_factory
    provider_registry = dict(providers or FIRST_PARTY_MODULES.retention_providers())
    if (
        selected_factory is None
        and providers is None
        and prowlarr is None
        and client_loader is None
    ):
        selected_factory = DefaultRuntimeFactory(
            environment=environment,
            http_client_factory=http_client_factory,
        )
    runtime = RuntimeResolver(
        factory=selected_factory,
        providers=provider_registry,
        prowlarr=prowlarr,
        client_loader=client_loader,
    )
    gateway = BackendControlGateway(
        sessions=sessions,
        cursor_secret=secret,
        runtime=runtime,
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
            if callable(close):
                close()
            engine.dispose()

    app.router.lifespan_context = lifespan
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.runtime = runtime
    app.state.gateway = gateway
    return app
