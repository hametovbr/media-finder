"""Framework-neutral persisted maintenance cadence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from .clock import Clock


class MaintenanceCoordinator(Protocol):
    def run(self, now: datetime) -> object: ...


@runtime_checkable
class MaintenanceStatePort(Protocol):
    def last_completed_at(self) -> datetime | None: ...

    def record_completed(self, completed_at: datetime) -> None: ...


class MaintenanceRunner:
    """Run generic maintenance at startup and at most once per day afterward."""

    def __init__(
        self,
        *,
        coordinator: MaintenanceCoordinator,
        state: MaintenanceStatePort,
        clock: Clock,
    ) -> None:
        self._coordinator = coordinator
        self._state = state
        self._clock = clock

    def run_at_startup(self) -> None:
        self._run(self._clock.now())

    def run_if_daily_due(self) -> bool:
        now = self._clock.now()
        completed = self._state.last_completed_at()
        if completed is not None and now - completed < timedelta(days=1):
            return False
        self._run(now)
        return True

    def _run(self, now: datetime) -> None:
        self._coordinator.run(now)
        self._state.record_completed(now)


__all__ = ["MaintenanceRunner", "MaintenanceStatePort"]
