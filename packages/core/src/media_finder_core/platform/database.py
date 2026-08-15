"""Shared SQLAlchemy metadata for context-owned persistence adapters."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single declarative registry for the core-owned database."""


__all__ = ["Base"]
