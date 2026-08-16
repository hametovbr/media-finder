"""Temporary compatibility exports for the server-owned processor adapter."""

from media_finder_server.processor_api import APIError
from media_finder_server.runtime import create_standalone_processor_app as create_app

__all__ = ["APIError", "create_app"]
