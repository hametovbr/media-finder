"""Safe application and module configuration primitives."""

import os
import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, SecretStr, field_validator
from sqlalchemy.orm import Session

from .models import AppSetting

ENV_REFERENCE = re.compile(r"^env:[A-Z][A-Z0-9_]*$")
URL = re.compile(r"https?://[^\s]+")


class EnvReference(BaseModel):
    """A persistable pointer to an environment variable, never its value."""

    value: str

    @field_validator("value")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if not ENV_REFERENCE.fullmatch(value):
            raise ValueError("must be an env:VARIABLE_NAME reference")
        return value

    @property
    def variable_name(self) -> str:
        return self.value.removeprefix("env:")


def resolve_env_reference(reference: EnvReference) -> SecretStr:
    value = os.environ.get(reference.variable_name)
    if value is None:
        raise ValueError("referenced environment variable is not set")
    return SecretStr(value)


def _safe_url(match: re.Match[str]) -> str:
    parsed = urlsplit(match.group(0))
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, hostname + port, "", "", ""))


def safe_url_origin(value: str) -> str | None:
    match = URL.search(value)
    if match is None:
        return None
    parsed = urlsplit(match.group(0))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, parsed.hostname + port, "", "", ""))


def redact(value: str, *, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Remove known secrets and credentials from diagnostic text."""

    safe = URL.sub(_safe_url, value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        safe = safe.replace(secret, "[REDACTED]")
    return safe


class SettingsRepository:
    """Persist configuration values while keeping resolved secrets out of storage."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def set_secret_reference(self, key: str, value: str) -> None:
        reference = EnvReference(value=value)
        setting = self.session.get(AppSetting, key)
        if setting is None:
            setting = AppSetting(key=key, value_payload={}, secret_reference=True)
            self.session.add(setting)
        setting.value_payload = {"reference": reference.value}
        setting.secret_reference = True
        self.session.commit()

    def get_reference(self, key: str) -> EnvReference | None:
        setting = self.session.get(AppSetting, key)
        if setting is None or not setting.secret_reference:
            return None
        return EnvReference(value=setting.value_payload["reference"])
