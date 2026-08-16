"""Isolated Manual metadata module contract."""

from __future__ import annotations

import ast
import email
import json
import os
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest
from media_finder_metadata_manual import registration
from media_finder_sdk import (
    Episode,
    EpisodeTableDocument,
    MediaKind,
    MetadataConformanceFixture,
    MetadataEditorConformanceFixture,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    ModuleError,
    ModuleErrorData,
    ModuleKind,
    NormalizedMetadata,
    Provenance,
    ProviderPayload,
    Season,
    SerializedMetadataProviderConformance,
    assert_metadata_editor_registration_conforms,
    assert_metadata_registration_conforms,
    load_manifest,
    parse_serialized_conformance_fixture,
    resolve_module_environment,
)

ROOT = Path(__file__).parents[4]
PACKAGE_ROOT = ROOT / "packages" / "modules" / "metadata-manual"
UV = ROOT / ".venv" / "Scripts" / "uv.exe"
UV_CACHE = ROOT / ".tools" / "uv-cache"
IDENTITY = "47e26ca2-f393-4a00-b33a-902d41d49714"


def _document(*, external_id: str = IDENTITY) -> dict[str, object]:
    return {
        "schema_version": "1",
        "external_id": external_id,
        "kind": "series",
        "locale": "en",
        "titles": {"en": "Local Animation", "ru": "Local Animation RU"},
        "plot": "A locally cataloged series.",
        "provider_ids": {"local": "animation-1"},
        "genres": ["Animation"],
        "seasons": [
            {
                "number": 0,
                "title": "Specials",
                "episodes": [
                    {
                        "number": 1,
                        "title": "Existing Special",
                        "air_date": "2025-01-01",
                    }
                ],
            }
        ],
    }


def _identity() -> MetadataIdentity:
    return MetadataIdentity(
        provider_id="manual",
        external_id=IDENTITY,
        media_kind=MediaKind.SERIES,
        locale="en",
    )


def _normalized(*, merged: bool = False) -> NormalizedMetadata:
    episodes = [Episode(number=1, title="Existing Special", air_date=date(2025, 1, 1))]
    if merged:
        episodes.append(
            Episode(
                number=2,
                title="Bonus",
                plot="Extra",
                air_date=date(2025, 2, 1),
                runtime_minutes=12,
            )
        )
    return NormalizedMetadata(
        kind=MediaKind.SERIES,
        titles={"en": "Local Animation", "ru": "Local Animation RU"},
        plot="A locally cataloged series.",
        provider_ids={"local": "animation-1"},
        genres=("Animation",),
        seasons=(Season(number=0, title="Specials", episodes=tuple(episodes)),),
        provenance=Provenance(
            provider_id="manual",
            external_id=IDENTITY,
            locale="en",
            source_label="manual",
        ),
        completeness=1.0,
        structural_quality=1.0,
    )


def test_manual_wheel_is_independent_and_contains_declared_resources(tmp_path: Path) -> None:
    environment = {**os.environ, "UV_CACHE_DIR": str(UV_CACHE)}
    destination = tmp_path / "wheels"
    completed = subprocess.run(
        [
            str(UV),
            "build",
            "--wheel",
            "--no-build-isolation",
            "--package",
            "media-finder-metadata-manual",
            "--out-dir",
            str(destination),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    wheel = next(destination.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = frozenset(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))
    package = "media_finder_metadata_manual"
    assert {
        f"{package}/__init__.py",
        f"{package}/module.toml",
        f"{package}/py.typed",
        f"{package}/translations/en.json",
        f"{package}/translations/ru.json",
        f"{package}/fixtures/conformance.json",
    } <= names
    requirements = tuple(metadata.get_all("Requires-Dist", []))
    assert any(value.lower().startswith("media-finder-module-sdk") for value in requirements)
    assert not any("media-finder-core" in value.lower() for value in requirements)
    manifest = load_manifest(PACKAGE_ROOT / "src/media_finder_metadata_manual/module.toml")
    assert metadata["Version"] == manifest.module_version

    target = tmp_path / "installed"
    subprocess.run(
        [str(UV), "pip", "install", "--target", str(target), "--no-deps", str(wheel)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    probe = "\n".join(
        (
            "import pathlib, sys",
            f"target = pathlib.Path({str(target)!r}).resolve()",
            "sys.path.insert(0, str(target))",
            "import media_finder_metadata_manual as module",
            "assert pathlib.Path(module.__file__).resolve().is_relative_to(target)",
            "assert module.__all__ == ['registration']",
        )
    )
    subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )


def test_manual_manifest_is_value_free_and_package_uses_only_public_sdk() -> None:
    manifest = load_manifest(PACKAGE_ROOT / "src/media_finder_metadata_manual/module.toml")

    assert manifest.module_id == "manual"
    assert manifest.module_kind is ModuleKind.METADATA_PROVIDER
    assert manifest.environment == ()
    assert manifest.capabilities == {
        "search",
        "fetch",
        "normalize",
        "retention",
        "metadata-edit",
    }
    assert manifest.attribution is not None
    assert manifest.attribution.notice_key == "module.manual.notice"

    forbidden = ("media_finder_core", "media_finder_control", "sqlalchemy", "fastapi")
    violations: list[str] = []
    for path in sorted((PACKAGE_ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            for name in imported:
                if name.startswith(forbidden):
                    violations.append(f"{path.name}:{node.lineno}:{name}")
    assert violations == []


def test_manual_provider_and_editor_pass_public_conformance() -> None:
    serialized = parse_serialized_conformance_fixture(
        (PACKAGE_ROOT / "src/media_finder_metadata_manual/fixtures/conformance.json").read_bytes()
    )
    assert isinstance(serialized, SerializedMetadataProviderConformance)
    document = _document()
    raw = ProviderPayload(data=document)
    identity = _identity()
    normalized = _normalized()
    module = registration(fixtures={(MediaKind.SERIES, IDENTITY, "en"): raw})
    success = serialized.success
    failures = {failure.operation: failure.error for failure in serialized.stable_failures}

    assert_metadata_registration_conforms(
        module,
        MetadataConformanceFixture(
            environment={},
            query=success.query,
            expected_results=success.results,
            identity=success.identity,
            expected_payload=raw,
            expected_metadata=success.normalized,
            invalid_identity=success.identity.model_copy(update={"external_id": "missing"}),
            expected_error_code=failures["fetch-invalid-identity"].code,
            created_at=success.retention.created_at,
            now=success.retention.now,
            expected_policy=success.retention.policy,
            expected_action=success.retention.action,
            expected_warning=success.retention.warning,
        ),
    )

    csv_document = EpisodeTableDocument.from_bytes(
        b"season,episode,title,plot,air_date,runtime_minutes\n0,2,Bonus,Extra,2025-02-01,12\n"
    )
    assert_metadata_editor_registration_conforms(
        module,
        MetadataEditorConformanceFixture(
            environment={},
            import_document=MetadataImportDocument.from_bytes(json.dumps(document).encode()),
            expected_import=MetadataEditResult(
                identity=identity,
                raw_payload=raw,
                metadata=normalized,
            ),
            invalid_document=MetadataImportDocument.from_bytes(
                b'{"schema_version":"1","external_id":"invalid"}'
            ),
            expected_error_code=failures["import-invalid-document"].code,
            current=normalized,
            episode_table=csv_document,
            expected_merge=MetadataEditResult(
                identity=identity,
                raw_payload=ProviderPayload(
                    data={"episode_table": csv_document.content().decode("utf-8")}
                ),
                metadata=_normalized(merged=True),
            ),
        ),
    )
    assert serialized.missing_configuration.applicable is False
    assert success.editor is not None
    assert success.editor.imported_identity == identity
    assert success.editor.merged_episode_count == sum(
        len(season.episodes) for season in _normalized(merged=True).seasons
    )

    provider = module.build(resolve_module_environment(module.manifest, {}))
    try:
        with pytest.raises(ModuleError) as invalid_identity:
            provider.fetch(success.identity.model_copy(update={"external_id": "missing"}))
    finally:
        provider.close()
    assert ModuleErrorData.from_error(invalid_identity.value) == failures["fetch-invalid-identity"]

    assert module.editor is not None
    editor = module.editor(resolve_module_environment(module.manifest, {}))
    with pytest.raises(ModuleError) as invalid_import:
        editor.import_document(
            MetadataImportDocument.from_bytes(b'{"schema_version":"1","external_id":"invalid"}')
        )
    assert ModuleErrorData.from_error(invalid_import.value) == failures["import-invalid-document"]


def test_invalid_episode_table_is_safe_and_does_not_mutate_current_metadata() -> None:
    module = registration()
    assert module.editor is not None
    editor = module.editor(resolve_module_environment(module.manifest, {}))
    current = _normalized()

    with pytest.raises(ModuleError) as raised:
        editor.merge_episode_table(
            current,
            EpisodeTableDocument.from_bytes(b"season,episode,title\n0,2,Valid\ninvalid,3,Broken\n"),
        )

    assert raised.value.code == "manual_import_invalid"
    assert current == _normalized()


def test_manual_serialized_redaction_probes_flow_through_identity_and_import_failures() -> None:
    serialized = parse_serialized_conformance_fixture(
        (PACKAGE_ROOT / "src/media_finder_metadata_manual/fixtures/conformance.json").read_bytes()
    )
    assert isinstance(serialized, SerializedMetadataProviderConformance)
    probes = serialized.redaction_probes
    module = registration()
    environment = resolve_module_environment(module.manifest, {})
    provider = module.build(environment)
    probe_identity = serialized.success.identity.model_copy(
        update={"external_id": probes.private_selection}
    )
    try:
        with pytest.raises(ModuleError) as identity_error:
            provider.fetch(probe_identity)
    finally:
        provider.close()

    assert module.editor is not None
    editor = module.editor(environment)
    probe_import = MetadataImportDocument.from_bytes(
        json.dumps(
            {
                "schema_version": "1",
                "external_id": probes.credential,
                "titles": {"en": probes.environment_value},
                "probe": probes.artifact_body,
            }
        ).encode()
    )
    with pytest.raises(ModuleError) as import_error:
        try:
            editor.import_document(probe_import)
        finally:
            editor.close()

    safe_public = " ".join(
        (
            ModuleErrorData.from_error(identity_error.value).model_dump_json(),
            ModuleErrorData.from_error(import_error.value).model_dump_json(),
            str(identity_error.value),
            str(import_error.value),
        )
    )
    for probe in probes.model_dump().values():
        assert probe not in safe_public
