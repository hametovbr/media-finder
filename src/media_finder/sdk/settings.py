"""Data-only descriptions used by core to render generic settings controls."""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, SecretStr, field_validator

ENV_REFERENCE = re.compile(r"^env:[A-Z][A-Z0-9_]*$")
SAFE_SERVICE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
SECRET_PATH_MARKERS = ("credential", "passkey", "secret", "session", "token")


class EnvReference(BaseModel):
    """Public persistable environment-variable pointer, never a resolved value."""

    value: str

    @field_validator("value")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if ENV_REFERENCE.fullmatch(value) is None:
            raise ValueError("must be an env:VARIABLE_NAME reference")
        return value

    @property
    def variable_name(self) -> str:
        return self.value.removeprefix("env:")


def validate_service_base_url(value: str, *, error_code: str) -> str:
    """Accept a safe HTTP origin plus an optional non-secret reverse-proxy path."""

    try:
        parsed = urlsplit(value)
        path = parsed.path or "/"
        secret_path = any(
            marker in segment.casefold()
            for segment in path.split("/")
            for marker in SECRET_PATH_MARKERS
        )
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or SAFE_SERVICE_PATH.fullmatch(path) is None
            or secret_path
        ):
            raise ValueError
        _ = parsed.port
    except (UnicodeError, ValueError):
        raise ValueError(error_code) from None
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class SettingsField:
    name: str
    title_key: str
    required: bool
    secret: bool
    order: int
    input_type: str
    html: None = None
    javascript: None = None


def describe_settings(config_model: type[BaseModel]) -> list[SettingsField]:
    fields: list[SettingsField] = []
    for name, definition in config_model.model_fields.items():
        extra = (
            definition.json_schema_extra if isinstance(definition.json_schema_extra, dict) else {}
        )
        annotation: Any = definition.annotation
        raw_order = extra.get("order", 100)
        order = raw_order if isinstance(raw_order, int) else 100
        fields.append(
            SettingsField(
                name=name,
                title_key=definition.title or f"settings.{name}",
                required=definition.is_required(),
                secret=bool(extra.get("secret")) or annotation is SecretStr,
                order=order,
                input_type="password"
                if bool(extra.get("secret")) or annotation is SecretStr
                else "text",
            )
        )
    return sorted(fields, key=lambda item: (item.order, item.name))
