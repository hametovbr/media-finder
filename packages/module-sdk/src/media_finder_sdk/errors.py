"""Stable and secret-safe module failure contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Annotated

from pydantic import Field, field_validator

from .common import PublicModel

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
    if isinstance(value, float) and not isfinite(value):
        raise TypeError("module_error_safe_detail_invalid")
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


class ModuleErrorData(PublicModel):
    """Serializable safe failure shape for conformance fixtures."""

    category: ModuleFailureCategory
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    safe_details: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("safe_details", mode="before")
    @classmethod
    def freeze_safe_details(cls, value: object) -> object:
        frozen = _freeze(value)
        if not isinstance(frozen, Mapping):
            raise ValueError("module_error_safe_details_invalid")
        return frozen

    @classmethod
    def from_error(cls, error: ModuleError) -> ModuleErrorData:
        return cls(
            category=error.category,
            code=error.code,
            safe_details=error.safe_details,
        )


__all__ = [
    "JsonScalar",
    "JsonValue",
    "ModuleError",
    "ModuleErrorData",
    "ModuleFailureCategory",
]
