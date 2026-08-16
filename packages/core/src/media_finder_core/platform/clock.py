"""Explicit application clock boundary."""

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Supply the current UTC time without hiding a global dependency."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


__all__ = ["Clock", "SystemClock"]
