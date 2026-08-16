"""Construction, caching, and lifecycle ownership for module capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from threading import RLock
from typing import Protocol

from media_finder_sdk import (
    DownloadClient,
    MetadataEditor,
    MetadataProvider,
    MetadataRetentionPolicy,
    ReleaseProvider,
    StaticModuleRegistry,
)

from .configuration import _EnvironmentResolver
from .diagnostics import _metadata_editor_unsupported, _module_runtime_closed
from .registry import _RegistryAccess


class _Closeable(Protocol):
    def close(self) -> None: ...


class ModuleRuntime:
    """Build, validate, cache, and close module capabilities exactly once."""

    def __init__(
        self,
        *,
        registry: StaticModuleRegistry,
        environment: Mapping[str, str],
    ) -> None:
        self._registrations = _RegistryAccess(registry)
        self._environment = _EnvironmentResolver(environment)
        self._metadata: dict[str, MetadataProvider] = {}
        self._editors: dict[str, MetadataEditor] = {}
        self._retention: dict[str, MetadataRetentionPolicy] = {}
        self._release: dict[str, ReleaseProvider] = {}
        self._download: dict[str, DownloadClient] = {}
        self._owned: list[_Closeable] = []
        self._lock = RLock()
        self._closed = False

    @property
    def registry(self) -> StaticModuleRegistry:
        return self._registrations.registry

    def metadata_provider(self, module_id: str) -> MetadataProvider:
        with self._lock:
            self._require_open()
            cached = self._metadata.get(module_id)
            if cached is not None:
                return cached
            registration = self._registrations.metadata(module_id)
        instance = registration.build(self._environment.resolve(registration.manifest))
        try:
            instance.validate()
        except BaseException:
            _close_failed_attempt(instance)
            raise
        return self._adopt(module_id, self._metadata, instance)

    def metadata_editor(self, module_id: str) -> MetadataEditor:
        with self._lock:
            self._require_open()
            cached = self._editors.get(module_id)
            if cached is not None:
                return cached
            registration = self._registrations.metadata(module_id)
            factory = registration.editor
            if factory is None:
                raise _metadata_editor_unsupported()
        instance = factory(self._environment.resolve(registration.manifest))
        return self._adopt(module_id, self._editors, instance)

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy:
        with self._lock:
            self._require_open()
            cached = self._retention.get(module_id)
            if cached is not None:
                return cached
            registration = self._registrations.metadata(module_id)
        instance = registration.retention()
        return self._adopt(module_id, self._retention, instance)

    def release_provider(self, module_id: str) -> ReleaseProvider:
        with self._lock:
            self._require_open()
            cached = self._release.get(module_id)
            if cached is not None:
                return cached
            registration = self._registrations.release(module_id)
        instance = registration.build(self._environment.resolve(registration.manifest))
        try:
            instance.validate()
        except BaseException:
            _close_failed_attempt(instance)
            raise
        return self._adopt(module_id, self._release, instance)

    def download_client(self, module_id: str) -> DownloadClient:
        with self._lock:
            self._require_open()
            cached = self._download.get(module_id)
            if cached is not None:
                return cached
            registration = self._registrations.download(module_id)
        instance = registration.build(self._environment.resolve(registration.manifest))
        try:
            instance.validate()
        except BaseException:
            _close_failed_attempt(instance)
            raise
        return self._adopt(module_id, self._download, instance)

    def _adopt[T: _Closeable](self, module_id: str, cache: dict[str, T], instance: T) -> T:
        with self._lock:
            if self._closed:
                selected = None
            else:
                selected = cache.get(module_id)
                if selected is None:
                    cache[module_id] = instance
                    self._owned.append(instance)
                    return instance
        _close_failed_attempt(instance)
        if selected is not None:
            return selected
        raise _module_runtime_closed()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            owned = tuple(reversed(self._owned))
            self._owned.clear()
            self._metadata.clear()
            self._editors.clear()
            self._retention.clear()
            self._release.clear()
            self._download.clear()
        first_error: BaseException | None = None
        for instance in owned:
            try:
                instance.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def _require_open(self) -> None:
        if self._closed:
            raise _module_runtime_closed()


def _close_failed_attempt(instance: _Closeable) -> None:
    # Construction/validation failure remains the actionable root cause.
    with suppress(BaseException):
        instance.close()


__all__ = ["ModuleRuntime"]
