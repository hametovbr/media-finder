"""Immutable resolution of manifest-declared environment values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import ModuleError, ModuleFailureCategory
from .manifest import ModuleManifest


@dataclass(frozen=True, slots=True, repr=False)
class _ResolvedValue:
    value: str
    secret: bool


class ResolvedModuleEnvironment:
    """Restricted runtime values available to one module factory."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, _ResolvedValue]) -> None:
        self._values = MappingProxyType(dict(values))

    def names(self) -> tuple[str, ...]:
        return tuple(self._values)

    def require(self, name: str) -> str:
        try:
            return self._values[name].value
        except KeyError as error:
            raise AttributeError("module_environment_name_undeclared") from error

    def optional(self, name: str) -> str | None:
        value = self._values.get(name)
        return None if value is None else value.value

    def __repr__(self) -> str:
        secret_names = tuple(name for name, value in self._values.items() if value.secret)
        return f"ResolvedModuleEnvironment(names={self.names()!r}, secret_names={secret_names!r})"


def resolve_module_environment(
    manifest: ModuleManifest,
    source: Mapping[str, str],
) -> ResolvedModuleEnvironment:
    """Copy exactly declared non-empty values from a process environment snapshot."""

    missing = tuple(
        declaration.name
        for declaration in manifest.environment
        if declaration.required and not source.get(declaration.name, "").strip()
    )
    if missing:
        raise ModuleError(
            category=ModuleFailureCategory.CONFIGURATION,
            code="module_environment_missing",
            safe_details={"missing_names": missing},
        )
    values = {
        declaration.name: _ResolvedValue(value=source[declaration.name], secret=declaration.secret)
        for declaration in manifest.environment
        if source.get(declaration.name, "").strip()
    }
    return ResolvedModuleEnvironment(values)


__all__ = ["ResolvedModuleEnvironment", "resolve_module_environment"]
