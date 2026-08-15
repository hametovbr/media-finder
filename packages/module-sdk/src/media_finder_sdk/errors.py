"""Stable and secret-safe module failure contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonValue, ...] | Mapping[str, JsonValue]

_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


class ModuleFailureCategory(StrEnum):
    """Stable coarse categories suitable for host-side translation."""

    CONFIGURATION = "configuration"
    INVALID_REQUEST = "invalid-request"
    INVALID_IDENTITY = "invalid-identity"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    LIMIT_EXCEEDED = "limit-exceeded"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"


def _freeze(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    raise TypeError("module_error_safe_detail_invalid")


class ModuleError(Exception):
    """Failure that exposes only a stable code and explicitly safe details."""

    __slots__ = ("category", "code", "safe_details")

    def __init__(
        self,
        *,
        category: ModuleFailureCategory,
        code: str,
        safe_details: Mapping[str, object] | None = None,
    ) -> None:
        if _ERROR_CODE.fullmatch(code) is None:
            raise ValueError("module_error_code_invalid")
        self.category = category
        self.code = code
        frozen = _freeze(safe_details or {})
        if not isinstance(frozen, Mapping):
            raise TypeError("module_error_safe_details_invalid")
        self.safe_details = frozen
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return (
            f"ModuleError(category={self.category!r}, code={self.code!r}, "
            f"safe_details={self.safe_details!r})"
        )


__all__ = ["JsonScalar", "JsonValue", "ModuleError", "ModuleFailureCategory"]
