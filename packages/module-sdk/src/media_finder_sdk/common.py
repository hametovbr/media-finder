"""Shared immutable public values for the module SDK."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PublicModel(BaseModel):
    """Strict immutable base for serializable SDK values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = ["PublicModel"]
