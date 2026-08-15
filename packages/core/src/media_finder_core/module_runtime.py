"""Core-owned lifecycle for statically registered trusted modules."""

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
    ModuleError,
    ModuleFailureCategory,
    ReleaseProvider,
    StaticModuleRegistry,
    resolve_module_environment,
)


class Closeable(Protocol):
    def close(self) -> None: ...


class ModuleRuntime:
    """Build, validate, cache, and close module capabilities exactly once."""

    def __init__(
        self,
        *,
        registry: StaticModuleRegistry,
        environment: Mapping[str, str],
    ) -> None:
        self._registry = registry
        self._environment = dict(environment)
        self._metadata: dict[str, MetadataProvider] = {}
        self._editors: dict[str, MetadataEditor] = {}
        self._retention: dict[str, MetadataRetentionPolicy] = {}
        self._release: dict[str, ReleaseProvider] = {}
        self._download: dict[str, DownloadClient] = {}
        self._owned: list[Closeable] = []
        self._lock = RLock()
        self._closed = False

    @property
    def registry(self) -> StaticModuleRegistry:
        return self._registry

    def metadata_provider(self, module_id: str) -> MetadataProvider:
        with self._lock:
            self._require_open()
            cached = self._metadata.get(module_id)
            if cached is not None:
                return cached
            registration = self._registry.metadata.get(module_id)
            if registration is None:
                raise _not_found()
        environment = resolve_module_environment(registration.manifest, self._environment)
        instance = registration.build(environment)
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
            registration = self._registry.metadata.get(module_id)
            if registration is None:
                raise _not_found()
            factory = registration.editor
            if factory is None:
                raise ModuleError(
                    category=ModuleFailureCategory.UNSUPPORTED,
                    code="metadata_editor_unsupported",
                )
        instance = factory(resolve_module_environment(registration.manifest, self._environment))
        return self._adopt(module_id, self._editors, instance)

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy:
        with self._lock:
            self._require_open()
            cached = self._retention.get(module_id)
            if cached is not None:
                return cached
            registration = self._registry.metadata.get(module_id)
            if registration is None:
                raise _not_found()
        instance = registration.retention()
        return self._adopt(module_id, self._retention, instance)

    def release_provider(self, module_id: str) -> ReleaseProvider:
        with self._lock:
            self._require_open()
            cached = self._release.get(module_id)
            if cached is not None:
                return cached
            registration = self._registry.release.get(module_id)
            if registration is None:
                raise _not_found()
        environment = resolve_module_environment(registration.manifest, self._environment)
        instance = registration.build(environment)
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
            registration = self._registry.download.get(module_id)
            if registration is None:
                raise _not_found()
        environment = resolve_module_environment(registration.manifest, self._environment)
        instance = registration.build(environment)
        try:
            instance.validate()
        except BaseException:
            _close_failed_attempt(instance)
            raise
        return self._adopt(module_id, self._download, instance)

    def _adopt[T: Closeable](self, module_id: str, cache: dict[str, T], instance: T) -> T:
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
        raise ModuleError(
            category=ModuleFailureCategory.UNAVAILABLE,
            code="module_runtime_closed",
        )

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
            raise ModuleError(
                category=ModuleFailureCategory.UNAVAILABLE,
                code="module_runtime_closed",
            )


def _not_found() -> ModuleError:
    return ModuleError(
        category=ModuleFailureCategory.INVALID_REQUEST,
        code="module_not_found",
    )


def _close_failed_attempt(
    instance: Closeable,
) -> None:
    # Construction/validation failure remains the actionable root cause.
    with suppress(BaseException):
        instance.close()


__all__ = ["ModuleRuntime"]
