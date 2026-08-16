"""Explicit processor-adapter resources for focused HTTP tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from media_finder_core.platform.database import create_database, session_factory
from media_finder_server.processor_api import create_processor_app


def create_processor_test_app(
    database_url: str,
    *,
    integration_token: str,
    clock: Callable[[], datetime] | None = None,
    retention_policies: Mapping[str, Any] | None = None,
) -> FastAPI:
    engine = create_database(database_url)
    sessions = session_factory(engine)
    application = create_processor_app(
        integration_token=integration_token,
        clock=clock,
        retention_policies=retention_policies,
        database_engine=engine,
        sessions=sessions,
    )
    application.state.test_owned_engine = engine
    return application


__all__ = ["create_processor_test_app"]
