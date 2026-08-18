"""Focused tests for the configurable process log level."""

from __future__ import annotations

import logging

import pytest
from media_finder_core.platform import ConfigurationError, CoreConfiguration
from media_finder_server.runtime import configure_logging


def _environment(log_level: str | None) -> dict[str, str]:
    environment: dict[str, str] = {
        "MEDIA_FINDER_UI_SECRET": "test-ui-secret",
        "MEDIA_FINDER_INTEGRATION_TOKEN": "test-integration-token",
    }
    if log_level is not None:
        environment["MEDIA_FINDER_LOG_LEVEL"] = log_level
    return environment


@pytest.fixture(autouse=True)
def _restore_root_level() -> object:
    original = logging.getLogger().level
    yield
    logging.getLogger().setLevel(original)


def test_log_level_default_and_validation() -> None:
    assert CoreConfiguration.from_environment(_environment(None)).log_level == "info"
    assert CoreConfiguration.from_environment(_environment("debug")).log_level == "debug"
    assert CoreConfiguration.from_environment(_environment("DEBUG")).log_level == "debug"
    assert CoreConfiguration.from_environment(_environment("Warning")).log_level == "warning"
    with pytest.raises(ConfigurationError) as invalid:
        CoreConfiguration.from_environment(_environment("verbose"))
    assert invalid.value.safe_details == {"variable": "MEDIA_FINDER_LOG_LEVEL"}


def test_configure_logging_sets_root_level() -> None:
    configure_logging("debug")
    assert logging.getLogger().level == logging.DEBUG
    configure_logging("error")
    assert logging.getLogger().level == logging.ERROR
