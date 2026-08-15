"""Safe application and module configuration primitives."""

import os
import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr

from .sdk.settings import EnvReference

__all__ = [
    "EnvReference",
    "redact",
    "resolve_env_reference",
    "safe_url_origin",
]

URL = re.compile(r"https?://[^\s]+")


def resolve_env_reference(reference: EnvReference) -> SecretStr:
    value = os.environ.get(reference.variable_name)
    if value is None:
        raise ValueError("referenced environment variable is not set")
    return SecretStr(value)


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        parsed_port = parsed.port
    except (UnicodeError, ValueError):
        return None
    port = f":{parsed_port}" if parsed_port is not None else ""
    return urlunsplit((parsed.scheme, parsed.hostname + port, "", "", ""))


def _safe_url(match: re.Match[str]) -> str:
    return _origin(match.group(0)) or "[REDACTED]"


def safe_url_origin(value: str) -> str | None:
    match = URL.search(value)
    if match is None:
        return None
    return _origin(match.group(0))


def redact(value: str, *, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Remove known secrets and credentials from diagnostic text."""

    safe = URL.sub(_safe_url, value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        safe = safe.replace(secret, "[REDACTED]")
    return safe
