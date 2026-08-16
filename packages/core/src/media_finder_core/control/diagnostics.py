"""Portable integration diagnostics and attribution projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from media_finder_control import ReadinessStatus
from media_finder_control.models import (
    AboutView,
    AttributionView,
    IntegrationDiagnostic,
    IntegrationVariableView,
)
from media_finder_sdk import EnvironmentVariableSpec

from media_finder_core.control.security import invoke

__all__ = [
    "AttributionSnapshot",
    "DiagnosticModuleSnapshot",
    "DiagnosticsControlModules",
    "DiagnosticsControlService",
]


@dataclass(frozen=True, slots=True)
class DiagnosticModuleSnapshot:
    module_id: str
    kind: Literal["metadata_provider", "download_client", "release_search"]
    declarations: tuple[EnvironmentVariableSpec, ...]
    ready: bool
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AttributionSnapshot:
    provider_id: str
    notice: str
    url: str | None = None


class DiagnosticsControlModules(Protocol):
    """Narrow safe diagnostic reads supplied by the host module runtime."""

    def diagnostic_modules(self) -> tuple[DiagnosticModuleSnapshot, ...]: ...

    def environment_is_set(self, name: str) -> bool: ...

    def attributions(self) -> tuple[AttributionSnapshot, ...]: ...


class DiagnosticsControlService:
    """Own readiness-state decisions, safe DTOs, and About projection."""

    def __init__(self, *, modules: DiagnosticsControlModules, build_version: str) -> None:
        self._modules = modules
        self._build_version = build_version

    async def integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]:
        return await invoke(
            self._integration_diagnostics,
            fallback="integration_diagnostics_unavailable",
        )

    def _integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]:
        values: list[IntegrationDiagnostic] = []
        for module in self._modules.diagnostic_modules():
            variables = tuple(
                IntegrationVariableView(
                    name=declaration.name,
                    required=declaration.required,
                    secret=declaration.secret,
                    is_set=self._modules.environment_is_set(declaration.name),
                    description_key=declaration.description_key,
                )
                for declaration in module.declarations
            )
            missing = any(value.required and not value.is_set for value in variables)
            status = (
                ReadinessStatus.MISSING
                if missing
                else ReadinessStatus.READY
                if module.ready
                else ReadinessStatus.UNAVAILABLE
            )
            values.append(
                IntegrationDiagnostic(
                    key=module.module_id,
                    kind=module.kind,
                    status=status,
                    error_code=(None if status is ReadinessStatus.READY else module.error_code),
                    variables=variables,
                )
            )
        return tuple(values)

    async def about(self) -> AboutView:
        return await invoke(self._about, fallback="about_unavailable")

    def _about(self) -> AboutView:
        return AboutView(
            version=self._build_version,
            attributions=tuple(
                AttributionView.model_validate(
                    {
                        "provider_key": value.provider_id,
                        "notice": value.notice,
                        "url": value.url,
                    }
                )
                for value in self._modules.attributions()
            ),
        )
