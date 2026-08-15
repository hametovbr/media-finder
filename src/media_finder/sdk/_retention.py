"""Internal provider-to-core retention persistence boundary."""

from dataclasses import dataclass
from typing import Any

from .types import NormalizedMetadata, RetentionExecution, RetentionPolicy


@dataclass(frozen=True, slots=True)
class InternalRetentionResult:
    """Carry private refresh material without making it an API response model."""

    outcome: RetentionExecution
    raw_payload: dict[str, Any] | None = None
    normalized: NormalizedMetadata | None = None
    policy: RetentionPolicy | None = None
