"""Framework-independent primitives shared by control consumers."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ControlModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Locale(StrEnum):
    EN = "en"
    RU = "ru"


class MediaKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"


class AcquisitionStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FAILED = "failed"


class ReadinessStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


class ControlError(ControlModel):
    code: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    request_id: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ControlFailure(Exception):
    """Language-neutral expected failure crossing the control boundary."""

    def __init__(
        self,
        *,
        code: str,
        status: int,
        details: dict[str, JsonValue] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status = status
        self.error = ControlError(
            code=code,
            request_id=request_id,
            details=details or {},
        )
        super().__init__(code)


class PageRequest(ControlModel):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = None


class Page[T](ControlModel):
    items: tuple[T, ...]
    next_cursor: str | None = None
