"""Living-documentation entry points for the modular architecture."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_architecture_and_module_authoring_guides_are_linked_from_entry_points() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    authoring = (ROOT / "docs" / "module-authoring.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    for distribution in (
        "media-finder-core",
        "media-finder-module-sdk",
        "media-finder-control-contracts",
        "media-finder-builtin-ui",
    ):
        assert distribution in architecture
    for contract in (
        "module.toml",
        "ResolvedModuleEnvironment",
        "fixtures/conformance.json",
        "assert_release_registration_conforms",
    ):
        assert contract in authoring
    assert "docs/architecture.md" in readme
    assert "docs/module-authoring.md" in readme
    assert "docs/module-authoring.md" in contributing
