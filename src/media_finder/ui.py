"""Composition root for the server-rendered browser interface."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .acquisition import ClientLoader
from .config import EnvReference, resolve_env_reference
from .db import create_database, session_factory
from .prowlarr import ProwlarrAdapter
from .sdk.protocols import MetadataProvider
from .ui_acquisition_routes import acquisition_router
from .ui_catalog_routes import catalog_router
from .ui_context import UIContext
from .ui_metadata_routes import metadata_router
from .ui_repository import UIRepository
from .ui_runtime import RuntimeFactory, RuntimeResolver
from .ui_security import SessionSigner, error_message, resolve_locale
from .ui_settings_routes import settings_router

__all__ = ["SessionSigner", "create_ui_app", "error_message", "resolve_locale"]

TEMPLATE_ROOT = Path(__file__).with_name("templates")
STATIC_ROOT = Path(__file__).with_name("static")


def create_ui_app(
    database_url: str,
    *,
    session_secret_reference: str,
    secure_cookie: bool = False,
    providers: dict[str, MetadataProvider] | None = None,
    prowlarr: ProwlarrAdapter | None = None,
    client_loader: ClientLoader | None = None,
    runtime_factory: RuntimeFactory | None = None,
    **_: Any,
) -> FastAPI:
    engine = create_database(database_url)
    secret_value = resolve_env_reference(EnvReference(value=session_secret_reference))
    signer = SessionSigner(secret_value.get_secret_value().encode())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(lifespan=lifespan)
    sessions = session_factory(engine)
    repository = UIRepository(sessions)
    provider_registry = dict(providers or {})
    runtime = RuntimeResolver(
        sessions,
        factory=runtime_factory,
        providers=provider_registry,
        prowlarr=prowlarr,
        client_loader=client_loader,
    )
    templates = Environment(
        loader=FileSystemLoader(TEMPLATE_ROOT),
        autoescape=select_autoescape(("html", "xml")),
        enable_async=False,
    )
    context = UIContext(
        sessions=sessions,
        repository=repository,
        runtime=runtime,
        templates=templates,
        signer=signer,
        secure_cookie=secure_cookie,
    )

    # Compatibility-only inspection hooks; route families depend on UIContext.
    app.state.engine = engine
    app.state.session_signer = signer
    app.state.sessions = sessions
    app.state.providers = provider_registry
    app.state.prowlarr = prowlarr
    app.state.client_loader = client_loader
    app.state.runtime = runtime
    app.state.metadata_selections = context.metadata_selections
    app.state.manual_drafts = context.manual_drafts

    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
    app.include_router(catalog_router(context))
    app.include_router(metadata_router(context))
    app.include_router(acquisition_router(context))
    app.include_router(settings_router(context))
    return app
