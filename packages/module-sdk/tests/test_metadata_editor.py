"""Optional metadata-editor capability contracts."""

from __future__ import annotations

import ast
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from media_finder_sdk import (
    EpisodeTableDocument,
    MediaKind,
    MetadataEditor,
    MetadataEditorConformanceFixture,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    MetadataProvider,
    MetadataProviderRegistration,
    MetadataRetentionPolicy,
    ModuleError,
    ModuleFailureCategory,
    NormalizedMetadata,
    Provenance,
    ProviderPayload,
    ResolvedModuleEnvironment,
    StaticModuleRegistry,
    assert_metadata_editor_registration_conforms,
    parse_manifest,
)

from .fixtures import manifest_toml

ROOT = Path(__file__).parents[3]


class _Lifecycle:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class _Editor(_Lifecycle):
    def __init__(self, expected: MetadataEditResult, merged: MetadataEditResult) -> None:
        super().__init__()
        self.expected = expected
        self.merged = merged

    def import_document(self, document: MetadataImportDocument) -> MetadataEditResult:
        if document.content() == b"invalid":
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_IDENTITY,
                code="fixture_import_invalid",
            )
        return self.expected

    def merge_episode_table(
        self,
        current: NormalizedMetadata,
        document: EpisodeTableDocument,
    ) -> MetadataEditResult:
        return self.merged


def _registration(*, capability: bool, editor: object | None) -> MetadataProviderRegistration:
    capabilities = ["search", "fetch", "normalize"]
    if capability:
        capabilities.append("metadata-edit")
    return MetadataProviderRegistration(
        manifest=parse_manifest(manifest_toml(capabilities=tuple(capabilities))),
        build=lambda _environment: pytest.fail("metadata provider must not be built"),
        retention=lambda: pytest.fail("retention policy must not be built"),
        editor=editor,  # type: ignore[arg-type]
    )


def _result(*, title: str = "Fixture") -> MetadataEditResult:
    identity = MetadataIdentity(
        provider_id="example-metadata",
        external_id="018e9db0-a912-4a79-a85e-50af784dd294",
        media_kind=MediaKind.SERIES,
        locale="en",
    )
    return MetadataEditResult(
        identity=identity,
        raw_payload=ProviderPayload(data={"title": title}),
        metadata=NormalizedMetadata(
            kind=MediaKind.SERIES,
            titles={"en": title},
            provenance=Provenance(
                provider_id=identity.provider_id,
                external_id=identity.external_id,
                locale=identity.locale,
                fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ),
    )


def test_editor_inputs_are_bounded_redacted_and_not_publicly_serializable() -> None:
    imported = MetadataImportDocument.from_bytes(b'{"title":"Fixture"}')
    episodes = EpisodeTableDocument.from_bytes(b"season,episode,title\n1,1,Pilot\n")

    assert imported.content() == b'{"title":"Fixture"}'
    assert episodes.content().startswith(b"season,episode")
    assert "Fixture" not in repr(imported)
    assert "Pilot" not in repr(episodes)
    assert not hasattr(imported, "model_dump")
    assert not hasattr(episodes, "model_dump")
    with pytest.raises(ValueError, match="metadata_import_document_too_large"):
        MetadataImportDocument.from_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="episode_table_document_too_large"):
        EpisodeTableDocument.from_bytes(b"x" * (1024 * 1024 + 1))


def test_editor_result_requires_consistent_identity_and_normalized_metadata() -> None:
    expected = _result()

    assert expected.identity.external_id == expected.metadata.provenance.external_id
    serialized = expected.model_dump(mode="json")
    assert serialized["raw_payload"]["data"] == {"title": "Fixture"}
    assert serialized["metadata"]["titles"] == {"en": "Fixture"}
    with pytest.raises(ValueError, match="metadata_edit_identity_mismatch"):
        MetadataEditResult(
            identity=expected.identity,
            raw_payload=expected.raw_payload,
            metadata=expected.metadata.model_copy(update={"kind": MediaKind.MOVIE}),
        )


def test_editor_protocol_is_specialized_and_registration_is_capability_matched() -> None:
    editor = _Editor(_result(), _result(title="Pilot"))

    assert isinstance(editor, MetadataEditor)
    assert not isinstance(editor, MetadataProvider)
    assert not isinstance(editor, MetadataRetentionPolicy)
    with pytest.raises(ValueError, match="metadata_editor_capability_mismatch"):
        StaticModuleRegistry.create(metadata=(_registration(capability=True, editor=None),))
    with pytest.raises(ValueError, match="metadata_editor_capability_mismatch"):
        StaticModuleRegistry.create(
            metadata=(
                _registration(
                    capability=False,
                    editor=lambda _environment: editor,
                ),
            )
        )


def test_metadata_editor_conformance_covers_import_merge_errors_and_cleanup() -> None:
    imported = _result()
    merged = _result(title="Pilot")
    editors: list[_Editor] = []

    def build_editor(_environment: ResolvedModuleEnvironment) -> MetadataEditor:
        editor = _Editor(imported, merged)
        editors.append(editor)
        return editor

    registration = _registration(capability=True, editor=build_editor)
    fixture = MetadataEditorConformanceFixture(
        environment={},
        import_document=MetadataImportDocument.from_bytes(b'{"title":"Fixture"}'),
        expected_import=imported,
        invalid_document=MetadataImportDocument.from_bytes(b"invalid"),
        expected_error_code="fixture_import_invalid",
        current=imported.metadata,
        episode_table=EpisodeTableDocument.from_bytes(b"season,episode,title\n1,1,Pilot\n"),
        expected_merge=merged,
    )

    assert_metadata_editor_registration_conforms(registration, fixture)

    assert editors[0].close_count == 2


def test_sdk_editor_surface_has_no_core_or_control_dependency() -> None:
    project = tomllib.loads((ROOT / "packages/module-sdk/pyproject.toml").read_text("utf-8"))
    assert set(project["project"]["dependencies"]) == {
        "packaging>=24,<26",
        "pydantic>=2.11,<3",
    }

    forbidden = ("media_finder_core", "media_finder_control", "sqlalchemy", "fastapi")
    violations: list[str] = []
    for path in sorted((ROOT / "packages/module-sdk/src").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.ImportFrom):
                imported = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden):
                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")
            if imported is not None and imported.startswith(forbidden):
                line = node.lineno if isinstance(node, ast.ImportFrom) else 0
                violations.append(f"{path.name}:{line}:{imported}")

    assert violations == []
