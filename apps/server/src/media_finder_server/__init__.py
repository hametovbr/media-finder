"""Production composition host for Media Finder.

The package root remains importable for build and metadata inspection without
eagerly importing the concrete integrations. Public composition attributes are
loaded only when a caller asks for them.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "ApplicationResources",
    "create_application",
    "create_module_registry",
    "run",
]

_MODULE_EXPORTS = frozenset(
    {
        "create_module_registry",
    }
)
_RUNTIME_EXPORTS = frozenset(
    {
        "ApplicationResources",
        "create_application",
        "run",
    }
)


def __getattr__(name: str) -> Any:
    if name in _MODULE_EXPORTS:
        return getattr(import_module(".modules", __name__), name)
    if name in _RUNTIME_EXPORTS:
        return getattr(import_module(".runtime", __name__), name)
    raise AttributeError(name)
