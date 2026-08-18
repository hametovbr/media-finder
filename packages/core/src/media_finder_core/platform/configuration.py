"""Strict process-only configuration owned by core composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import SecretStr

from .errors import SafeError

DEFAULT_DATABASE_URL = "sqlite:////data/media-finder.db"
DEFAULT_LOG_LEVEL = "info"
ALLOWED_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


class ConfigurationError(SafeError):
    """A core environment value is absent or invalid."""


@dataclass(frozen=True, slots=True)
class CoreConfiguration:
    database_url: str
    ui_mode: str
    log_level: str
    secure_cookie: bool
    ui_secret: SecretStr
    integration_token: SecretStr

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> CoreConfiguration:
        database_url = environment.get("MEDIA_FINDER_DATABASE_URL", DEFAULT_DATABASE_URL)
        if not database_url.strip():
            raise _invalid("MEDIA_FINDER_DATABASE_URL")

        ui_mode = environment.get("MEDIA_FINDER_UI_MODE", "builtin")
        if ui_mode not in {"builtin", "disabled"}:
            raise _invalid("MEDIA_FINDER_UI_MODE")

        log_level = environment.get("MEDIA_FINDER_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().lower()
        if log_level not in ALLOWED_LOG_LEVELS:
            raise _invalid("MEDIA_FINDER_LOG_LEVEL")

        cookie_value = environment.get("MEDIA_FINDER_SECURE_COOKIE", "true")
        if cookie_value == "true":
            secure_cookie = True
        elif cookie_value == "false":
            secure_cookie = False
        else:
            raise _invalid("MEDIA_FINDER_SECURE_COOKIE")

        ui_secret = _required(environment, "MEDIA_FINDER_UI_SECRET")
        integration_token = _required(environment, "MEDIA_FINDER_INTEGRATION_TOKEN")
        return cls(
            database_url=database_url,
            ui_mode=ui_mode,
            log_level=log_level,
            secure_cookie=secure_cookie,
            ui_secret=SecretStr(ui_secret),
            integration_token=SecretStr(integration_token),
        )


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise _invalid(name)
    return value


def _invalid(variable: str) -> ConfigurationError:
    return ConfigurationError(
        code="core_configuration_invalid",
        safe_details={"variable": variable},
    )


__all__ = [
    "ALLOWED_LOG_LEVELS",
    "DEFAULT_DATABASE_URL",
    "DEFAULT_LOG_LEVEL",
    "ConfigurationError",
    "CoreConfiguration",
]
