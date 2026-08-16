"""Host-only first-party composition and core-owned module lifecycle."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadClientRegistration,
    DownloadDestination,
    EnvironmentVariableSpec,
    ModuleError,
    ModuleFailureCategory,
    ModuleKind,
    ModuleManifest,
    ReleaseProviderRegistration,
    ResolvedModuleEnvironment,
    StaticModuleRegistry,
    SubmissionResult,
)

ROOT = Path(__file__).parents[1]
CORE_ROOTS = (ROOT / "packages" / "core" / "src",)
CONCRETE_PACKAGES = {
    "media_finder_metadata_manual",
    "media_finder_metadata_tmdb",
    "media_finder_release_prowlarr",
    "media_finder_download_qbittorrent",
}
CONCRETE_IDS = {"manual", "tmdb", "prowlarr", "qbittorrent"}


class FixtureDownloadClient:
    def __init__(
        self,
        *,
        validation_error: bool = False,
        close_error: bool = False,
    ) -> None:
        self.validation_error = validation_error
        self.close_error = close_error
        self.validate_calls = 0
        self.close_calls = 0

    def validate(self) -> None:
        self.validate_calls += 1
        if self.validation_error:
            raise ModuleError(
                category=ModuleFailureCategory.UNAVAILABLE,
                code="fixture_validation_failed",
            )

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (DownloadDestination(key="fixture", label="Fixture"),)

    def submit(
        self,
        artifact: DownloadArtifact,
        destination: str,
        correlation: str,
    ) -> SubmissionResult:
        del artifact, destination
        return SubmissionResult(accepted=True, correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(found=False, correlation=correlation)

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error:
            raise RuntimeError("fixture_close_failed")


class RecordingDownloadFactory:
    def __init__(
        self,
        *,
        validation_error: bool = False,
        close_error: bool = False,
    ) -> None:
        self.validation_error = validation_error
        self.close_error = close_error
        self.environment_names: list[tuple[str, ...]] = []
        self.environment_values: list[dict[str, str]] = []
        self.instances: list[FixtureDownloadClient] = []

    def __call__(self, environment: ResolvedModuleEnvironment) -> FixtureDownloadClient:
        names = environment.names()
        self.environment_names.append(names)
        self.environment_values.append({name: environment.require(name) for name in names})
        with pytest.raises(AttributeError, match="module_environment_name_undeclared"):
            environment.require("UNDECLARED_SECRET")
        instance = FixtureDownloadClient(
            validation_error=self.validation_error,
            close_error=self.close_error,
        )
        self.instances.append(instance)
        return instance


def _manifest(
    module_id: str,
    environment: tuple[EnvironmentVariableSpec, ...],
) -> ModuleManifest:
    translation_keys = {f"module.{module_id}.name"}
    translation_keys.update(item.description_key for item in environment)
    return ModuleManifest(
        module_id=module_id,
        module_kind=ModuleKind.DOWNLOAD_CLIENT,
        module_version="0.1.0",
        sdk_compatibility=">=1,<2",
        contract_version="1",
        name_key=f"module.{module_id}.name",
        capabilities={"destinations", "submit", "correlation", "magnet"},
        translation_keys=translation_keys,
        environment=environment,
    )


def _download_registration(
    module_id: str,
    variable: EnvironmentVariableSpec,
    factory: RecordingDownloadFactory,
) -> DownloadClientRegistration:
    return DownloadClientRegistration(
        manifest=_manifest(module_id, (variable,)),
        build=factory,
    )


def _host_registry() -> StaticModuleRegistry:
    import media_finder_server

    factory = getattr(media_finder_server, "create_module_registry", None)
    assert callable(factory), "server host must publish create_module_registry()"
    registry = factory()
    assert isinstance(registry, StaticModuleRegistry)
    return registry


def _module_runtime_type():
    import media_finder_core

    runtime = getattr(media_finder_core, "ModuleRuntime", None)
    assert runtime is not None, "core must publish ModuleRuntime"
    return runtime


def test_server_host_assembles_one_immutable_typed_first_party_registry() -> None:
    registry = _host_registry()

    assert set(registry.metadata) == {"manual", "tmdb"}
    assert set(registry.release) == {"prowlarr"}
    assert set(registry.download) == {"qbittorrent"}
    assert {value.manifest.module_kind for value in registry.metadata.values()} == {
        ModuleKind.METADATA_PROVIDER
    }
    assert registry.release["prowlarr"].manifest.module_kind is ModuleKind.RELEASE_PROVIDER
    assert registry.download["qbittorrent"].manifest.module_kind is ModuleKind.DOWNLOAD_CLIENT

    with pytest.raises(TypeError):
        registry.metadata["other"] = registry.metadata["manual"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        registry.download = {}  # type: ignore[misc]


def test_sdk_registry_rejects_duplicate_identity_wrong_kind_and_environment_conflicts() -> None:
    token = EnvironmentVariableSpec(
        name="SHARED_TOKEN",
        required=True,
        secret=True,
        description_key="module.fixture.environment.token",
    )
    healthy = _download_registration("healthy", token, RecordingDownloadFactory())

    with pytest.raises(ValueError, match="module_identity_duplicate"):
        StaticModuleRegistry.create(download=(healthy, healthy))

    wrong_kind = ReleaseProviderRegistration(
        manifest=healthy.manifest,
        build=lambda environment: pytest.fail(f"unexpected build: {environment!r}"),
    )
    with pytest.raises(ValueError, match="module_registration_kind_mismatch"):
        StaticModuleRegistry.create(release=(wrong_kind,))

    conflicting_token = token.model_copy(
        update={
            "secret": False,
            "description_key": "module.conflict.environment.token",
        }
    )
    conflicting = _download_registration(
        "conflict",
        conflicting_token,
        RecordingDownloadFactory(),
    )
    with pytest.raises(ValueError, match="module_environment_conflict"):
        StaticModuleRegistry.create(download=(healthy, conflicting))


def test_core_runtime_passes_only_declared_environment_and_caches_success() -> None:
    healthy_factory = RecordingDownloadFactory()
    healthy_variable = EnvironmentVariableSpec(
        name="HEALTHY_TOKEN",
        required=True,
        secret=True,
        description_key="module.healthy.environment.token",
    )
    registry = StaticModuleRegistry.create(
        download=(_download_registration("healthy", healthy_variable, healthy_factory),)
    )
    runtime_type = _module_runtime_type()
    runtime = runtime_type(
        registry=registry,
        environment={
            "HEALTHY_TOKEN": "healthy-secret",
            "UNDECLARED_SECRET": "must-not-be-visible",
        },
    )

    try:
        first = runtime.download_client("healthy")
        second = runtime.download_client("healthy")
    finally:
        runtime.close()
        runtime.close()

    assert first is second
    assert healthy_factory.environment_names == [("HEALTHY_TOKEN",)]
    assert healthy_factory.environment_values == [{"HEALTHY_TOKEN": "healthy-secret"}]
    assert healthy_factory.instances[0].validate_calls == 1
    assert healthy_factory.instances[0].close_calls == 1


def test_failed_attempt_closes_its_instance_without_affecting_cached_sibling() -> None:
    healthy_factory = RecordingDownloadFactory()
    failing_factory = RecordingDownloadFactory(validation_error=True)
    healthy_variable = EnvironmentVariableSpec(
        name="HEALTHY_TOKEN",
        required=True,
        secret=True,
        description_key="module.healthy.environment.token",
    )
    failing_variable = EnvironmentVariableSpec(
        name="FAILING_TOKEN",
        required=True,
        secret=True,
        description_key="module.failing.environment.token",
    )
    registry = StaticModuleRegistry.create(
        download=(
            _download_registration("healthy", healthy_variable, healthy_factory),
            _download_registration("failing", failing_variable, failing_factory),
        )
    )
    runtime_type = _module_runtime_type()
    runtime = runtime_type(
        registry=registry,
        environment={
            "HEALTHY_TOKEN": "healthy-secret",
            "FAILING_TOKEN": "failing-secret",
            "UNDECLARED_SECRET": "must-not-be-visible",
        },
    )

    healthy = runtime.download_client("healthy")
    with pytest.raises(ModuleError, match="fixture_validation_failed"):
        runtime.download_client("failing")
    with pytest.raises(ModuleError, match="fixture_validation_failed"):
        runtime.download_client("failing")

    assert runtime.download_client("healthy") is healthy
    assert healthy_factory.instances[0].close_calls == 0
    assert [instance.close_calls for instance in failing_factory.instances] == [1, 1]

    runtime.close()
    runtime.close()
    assert healthy_factory.instances[0].close_calls == 1
    assert [instance.close_calls for instance in failing_factory.instances] == [1, 1]


def test_shutdown_continues_closing_siblings_after_one_close_failure() -> None:
    first_factory = RecordingDownloadFactory()
    failing_factory = RecordingDownloadFactory(close_error=True)
    first_variable = EnvironmentVariableSpec(
        name="FIRST_TOKEN",
        required=True,
        secret=True,
        description_key="module.first.environment.token",
    )
    failing_variable = EnvironmentVariableSpec(
        name="FAILING_CLOSE_TOKEN",
        required=True,
        secret=True,
        description_key="module.failing-close.environment.token",
    )
    registry = StaticModuleRegistry.create(
        download=(
            _download_registration("first", first_variable, first_factory),
            _download_registration("failing-close", failing_variable, failing_factory),
        )
    )
    runtime_type = _module_runtime_type()
    runtime = runtime_type(
        registry=registry,
        environment={
            "FIRST_TOKEN": "first-secret",
            "FAILING_CLOSE_TOKEN": "failing-secret",
        },
    )
    runtime.download_client("first")
    runtime.download_client("failing-close")

    with pytest.raises(RuntimeError, match="fixture_close_failed"):
        runtime.close()
    runtime.close()

    assert first_factory.instances[0].close_calls == 1
    assert failing_factory.instances[0].close_calls == 1


def test_validation_failure_remains_primary_when_attempt_cleanup_also_fails() -> None:
    failing_factory = RecordingDownloadFactory(validation_error=True, close_error=True)
    variable = EnvironmentVariableSpec(
        name="FAILING_TOKEN",
        required=True,
        secret=True,
        description_key="module.failing.environment.token",
    )
    registry = StaticModuleRegistry.create(
        download=(_download_registration("failing", variable, failing_factory),)
    )
    runtime_type = _module_runtime_type()
    runtime = runtime_type(registry=registry, environment={"FAILING_TOKEN": "secret"})

    with pytest.raises(ModuleError, match="fixture_validation_failed"):
        runtime.download_client("failing")

    assert failing_factory.instances[0].close_calls == 1
    runtime.close()


def test_core_sources_have_no_concrete_imports_or_module_id_branches() -> None:
    violations: list[str] = []

    for source_root in CORE_ROOTS:
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = (node.module,)
                for module in imported:
                    if any(
                        module == concrete or module.startswith(f"{concrete}.")
                        for concrete in CONCRETE_PACKAGES
                    ):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{module}")

                if isinstance(node, ast.If | ast.IfExp | ast.Match):
                    identifiers = {
                        child.value
                        for child in ast.walk(node)
                        if isinstance(child, ast.Constant) and isinstance(child.value, str)
                    }
                    concrete = sorted(identifiers & CONCRETE_IDS)
                    if concrete:
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}:branch={concrete!r}"
                        )

    assert violations == []


def test_server_registry_factory_accepts_no_runtime_service_container() -> None:
    import inspect

    import media_finder_server

    factory = getattr(media_finder_server, "create_module_registry", None)
    assert callable(factory), "server host must publish create_module_registry()"
    signature = inspect.signature(factory)

    assert tuple(signature.parameters) == ()


def test_server_runtime_uses_the_typed_registry_as_its_single_module_lifecycle() -> None:
    from media_finder_core import ModuleRuntime
    from media_finder_core.acquisition import ReleaseSelectionCache
    from media_finder_server.modules import create_runtime_module_composition

    composition = create_runtime_module_composition(
        environment={},
        release_cache=ReleaseSelectionCache(),
    )
    runtime = composition.runtime
    assert isinstance(runtime, ModuleRuntime)
    assert set(runtime.registry.metadata) == {"manual", "tmdb"}
    assert set(runtime.registry.release) == {"prowlarr"}
    assert set(runtime.registry.download) == {"qbittorrent"}

    composition.release_selections.close()
    runtime.close()
    runtime.close()
