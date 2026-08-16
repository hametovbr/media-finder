"""Deterministic gettext compilation and checked-catalog drift behavior."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "build_locales.py"
SOURCE = ROOT / "packages" / "builtin-ui" / "src" / "media_finder_builtin_ui" / "locales"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_checked_catalogs_are_byte_stable_and_build_repairs_drift(tmp_path: Path) -> None:
    first = _run("--check")
    assert first.returncode == 0, first.stderr or first.stdout

    catalogs = tmp_path / "locales"
    shutil.copytree(SOURCE, catalogs)
    corrupt = catalogs / "ru" / "LC_MESSAGES" / "messages.mo"
    corrupt.write_bytes(b"not-a-gettext-catalog")
    drift = _run("--check", "--catalog-root", str(catalogs))
    assert drift.returncode == 1
    assert "ru/LC_MESSAGES/messages.mo" in drift.stderr.replace("\\", "/")

    rebuilt = _run("--catalog-root", str(catalogs))
    assert rebuilt.returncode == 0, rebuilt.stderr or rebuilt.stdout
    first_bytes = corrupt.read_bytes()
    repeated = _run("--catalog-root", str(catalogs))
    assert repeated.returncode == 0, repeated.stderr or repeated.stdout
    assert corrupt.read_bytes() == first_bytes
    assert _run("--check", "--catalog-root", str(catalogs)).returncode == 0


def test_repository_exposes_localization_build_and_drift_commands() -> None:
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["locales:build"] == "uv run --frozen python scripts/build_locales.py"
    assert scripts["locales:check"] == ("uv run --frozen python scripts/build_locales.py --check")


def test_locale_compiler_rejects_a_babel_version_different_from_the_lock(tmp_path: Path) -> None:
    from scripts.build_locales import assert_locked_babel

    mismatched = tmp_path / "uv.lock"
    mismatched.write_text(
        'version = 1\n[[package]]\nname = "babel"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="babel_version_does_not_match_uv_lock"):
        assert_locked_babel(mismatched)
