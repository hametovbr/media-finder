"""Production composition entry point for the current legacy application shell."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from fastapi import FastAPI
from media_finder.integration_runtime import DefaultRuntimeFactory
from media_finder.runtime import create_application as _create_application
from media_finder.runtime import run as _run
from media_finder.ui import create_ui_app as _create_ui_app

from .modules import (
    create_legacy_module_registry,
    create_release_registration,
    create_runtime_module_composition,
)


def create_runtime_factory(
    *,
    http_client_factory: Callable[[], httpx.Client] = httpx.Client,
    environment: Mapping[str, str] | None = None,
) -> DefaultRuntimeFactory:
    snapshot = dict(os.environ if environment is None else environment)
    composition = create_runtime_module_composition(
        environment=snapshot,
        client_factory=http_client_factory,
    )
    return DefaultRuntimeFactory(
        http_client_factory=http_client_factory,
        registry=composition.legacy_registry,
        release_registration_factory=composition.release_registration_factory,
        environment=snapshot,
        lifecycle=composition.runtime,
        module_runtime=composition.runtime,
    )


def create_application() -> FastAPI:
    runtime_factory = create_runtime_factory()
    try:
        return _create_application(
            registry=runtime_factory.registry,
            runtime_factory=runtime_factory,
        )
    except BaseException:
        runtime_factory.close()
        raise


def create_ui_app(database_url: str, **options: Any) -> FastAPI:
    runtime_factory = options.pop("runtime_factory", None)
    owns_runtime_factory = False
    uses_explicit_test_capabilities = any(
        options.get(name) is not None for name in ("providers", "prowlarr", "client_loader")
    )
    if runtime_factory is None and not uses_explicit_test_capabilities:
        runtime_factory = create_runtime_factory(
            http_client_factory=options.get("http_client_factory", httpx.Client),
            environment=options.get("environment"),
        )
        owns_runtime_factory = True
    registry = (
        runtime_factory.registry
        if isinstance(runtime_factory, DefaultRuntimeFactory)
        else create_legacy_module_registry()
    )
    try:
        return _create_ui_app(
            database_url,
            registry=registry,
            release_registration_factory=create_release_registration,
            runtime_factory=runtime_factory,
            **options,
        )
    except BaseException:
        if owns_runtime_factory and runtime_factory is not None:
            runtime_factory.close()
        raise


def run() -> None:
    runtime_factory = create_runtime_factory()
    try:
        _run(
            registry=runtime_factory.registry,
            runtime_factory=runtime_factory,
        )
    finally:
        runtime_factory.close()


__all__ = ["create_application", "create_runtime_factory", "create_ui_app", "run"]
