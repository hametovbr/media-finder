"""Explicit built-in UI test host over typed core and module resources."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from gateway_fixtures import create_gateway
from media_finder_builtin_ui import BuiltinUIOptions, create_builtin_ui
from media_finder_core.platform.database import create_database, session_factory
from media_finder_server.control_security import BackendBrowserSecurity


def create_ui_test_app(
    database_url: str,
    *,
    session_secret: str | None = None,
    session_secret_reference: str | None = None,
    secure_cookie: bool = False,
    providers: Mapping[str, object] | None = None,
    acquisition: object | None = None,
    environment: Mapping[str, str] | None = None,
    **_: Any,
) -> FastAPI:
    secret = _secret(session_secret, session_secret_reference)
    engine = create_database(database_url)
    sessions = session_factory(engine)
    effective_environment = dict(environment or {})
    with sessions() as session:
        selected_providers = tuple(providers.values()) if providers else ()
        releases = None
        download_client = None
        release_id = "fixture-release"
        release_version = "1.2.3"
        download_id = "fixture-download"
        download_version = "9.8.7"
        release_manifest = None
        download_manifest = None
        if acquisition is not None:
            try:
                releases = acquisition.release_selections()
            except Exception:
                releases = None
            try:
                download_client = acquisition.download_client()
            except Exception:
                download_client = None
            release = acquisition.release_module()
            download = acquisition.download_module()
            release_manifest = acquisition.release_manifest
            download_manifest = acquisition.download_manifest
            for manifest in (release_manifest, download_manifest):
                for declaration in manifest.environment:
                    effective_environment.setdefault(
                        declaration.name,
                        (
                            f"https://{manifest.module_id}.fixture.test"
                            if declaration.name.endswith("_URL")
                            else f"{manifest.module_id}-fixture-value"
                        ),
                    )
            release_id = release.module_id
            release_version = release.module_version
            download_id = download.module_id
            download_version = download.module_version
        gateway = create_gateway(
            session,
            metadata_providers=selected_providers,
            release_selections=releases,
            download_client=download_client,
            release_id=release_id,
            release_version=release_version,
            download_id=download_id,
            download_version=download_version,
            release_manifest=release_manifest,
            download_manifest=download_manifest,
            environment=effective_environment,
        )
    security = BackendBrowserSecurity(secret=secret.encode())
    application = create_builtin_ui(
        gateway=gateway,
        security=security,
        options=BuiltinUIOptions(secure_cookie=secure_cookie),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        try:
            yield
        finally:
            gateway._test_release_selections.close()  # type: ignore[attr-defined]
            gateway._test_runtime.close()  # type: ignore[attr-defined]
            engine.dispose()

    application.router.lifespan_context = lifespan
    application.state.engine = engine
    application.state.sessions = sessions
    application.state.gateway = gateway
    return application


def _secret(value: str | None, reference: str | None) -> str:
    if value is not None:
        return value
    if reference is None or not reference.startswith("env:"):
        raise ValueError("session_secret_reference_invalid")
    selected = os.environ.get(reference.removeprefix("env:"))
    if not selected:
        raise ValueError("session_secret_unavailable")
    return selected


__all__ = ["create_ui_test_app"]
