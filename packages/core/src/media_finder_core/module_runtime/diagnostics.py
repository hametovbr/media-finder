"""Stable errors emitted by the core module runtime."""

from media_finder_sdk import ModuleError, ModuleFailureCategory


def _module_not_found() -> ModuleError:
    return ModuleError(
        category=ModuleFailureCategory.INVALID_REQUEST,
        code="module_not_found",
    )


def _metadata_editor_unsupported() -> ModuleError:
    return ModuleError(
        category=ModuleFailureCategory.UNSUPPORTED,
        code="metadata_editor_unsupported",
    )


def _module_runtime_closed() -> ModuleError:
    return ModuleError(
        category=ModuleFailureCategory.UNAVAILABLE,
        code="module_runtime_closed",
    )


__all__: list[str] = []
