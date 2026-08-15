"""Safe module error contracts."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModuleError(Exception):
    code: str
    message: str
    safe_details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
