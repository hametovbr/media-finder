"""Mechanical inventory checks for the repository-owned skill catalog."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILLS = ROOT / ".agents" / "skills"

GENERATED_OPEN_SPEC_SKILLS = {
    "openspec-apply-change",
    "openspec-archive-change",
    "openspec-explore",
    "openspec-propose",
    "openspec-sync-specs",
    "openspec-update-change",
}
DOMAIN_SKILLS = {
    "adding-download-client",
    "adding-metadata-provider",
    "adding-release-provider",
    "evolving-metadata-schema",
}
CROSS_CUTTING_SKILLS = {
    "debugging-media-finder-failures",
    "developing-media-finder-changes",
    "evolving-media-finder-contracts",
    "maintaining-media-finder-skills",
    "making-pragmatic-media-finder-decisions",
    "reviewing-media-finder-changes",
    "verifying-and-publishing-media-finder",
}
MANUAL_SKILLS = DOMAIN_SKILLS | CROSS_CUTTING_SKILLS

FRONTMATTER_NAME = re.compile(r"^---\nname: ([a-z0-9-]+)\n", re.MULTILINE)
PRODUCT_RELEASE_LITERAL = re.compile(r"(?<![A-Za-z0-9])v?\d+\.\d+\.\d+(?![A-Za-z0-9])")
WORKSTATION_PATH = re.compile(r"(?:[A-Za-z]:\\Users\\|/Users/|/home/)[^\s`]+")


def test_project_skill_inventory_has_all_approved_routes() -> None:
    actual = {path.name for path in SKILLS.iterdir() if path.is_dir()}

    assert actual == GENERATED_OPEN_SPEC_SKILLS | MANUAL_SKILLS


def test_manual_skills_have_matching_frontmatter_and_codex_metadata() -> None:
    for name in sorted(MANUAL_SKILLS):
        skill = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        metadata = (SKILLS / name / "agents" / "openai.yaml").read_text(encoding="utf-8")

        match = FRONTMATTER_NAME.search(skill)
        assert match is not None, name
        assert match.group(1) == name
        assert "\ndescription: Use when" in skill
        assert 'display_name: "' in metadata
        assert 'short_description: "' in metadata
        assert f'default_prompt: "Use ${name} ' in metadata


def test_manual_skills_are_portable_across_devices_and_releases() -> None:
    for name in sorted(MANUAL_SKILLS):
        skill = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")

        assert WORKSTATION_PATH.search(skill) is None, name
        assert PRODUCT_RELEASE_LITERAL.search(skill) is None, name


def test_agents_routes_every_manual_skill() -> None:
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for name in sorted(MANUAL_SKILLS):
        assert f"`{name}`" in instructions
