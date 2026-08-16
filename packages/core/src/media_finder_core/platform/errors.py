"""Framework-neutral safe errors and diagnostic redaction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlsplit, urlunsplit

type SafeDetail = (
    str | int | float | bool | tuple["SafeDetail", ...] | Mapping[str, "SafeDetail"] | None
)
URL = re.compile(r"https?://[^\s]+")
CODE = re.compile(r"^[a-z][a-z0-9_]{0,199}$")


def _freeze(value: object) -> SafeDetail:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, SafeDetail] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("safe_error_detail_invalid")
            frozen[key] = _freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    raise TypeError("safe_error_detail_invalid")


class SafeError(Exception):
    """Stable machine error containing only immutable allowlisted details."""

    def __init__(self, *, code: str, safe_details: Mapping[str, object] | None = None) -> None:
        if CODE.fullmatch(code) is None:
            raise ValueError("safe_error_code_invalid")
        frozen = _freeze(safe_details or {})
        if not isinstance(frozen, Mapping):  # pragma: no cover - construction guarantees it
            raise TypeError("safe_error_detail_invalid")
        self.code = code
        self.safe_details = frozen
        super().__init__(code)


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


def redact(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Remove credentials, paths, queries, fragments, and known secrets."""

    safe = URL.sub(_safe_url, value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        safe = safe.replace(secret, "[REDACTED]")
    return safe


def safe_code(value: str, *, fallback: str) -> str:
    """Return a bounded machine code or a caller-owned safe fallback."""

    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not value or len(value) > 200 or any(character not in allowed for character in value):
        return fallback
    return value


__all__ = ["SafeError", "redact", "safe_code"]
