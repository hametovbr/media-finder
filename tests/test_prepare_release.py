"""Deterministic stable-release candidate preparation contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
# Every fixture is a `git archive HEAD` of this checkout, so the baseline version
# is read from the committed tree rather than the working copy, and the requested
# version follows from it. The suite therefore passes whatever version the tree
# carries and never pins the one it carried when it was written.
BASE_VERSION = subprocess.run(
    ["git", "show", "HEAD:VERSION"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
PREVIOUS_STABLE_TAG = f"v{BASE_VERSION}"


def _next_version(value: str) -> str:
    major, minor, _patch = (int(part) for part in value.split("."))
    return f"{major}.{minor + 1}.0"


NEXT_VERSION = _next_version(BASE_VERSION)
BASE_VERSION_PATTERN = BASE_VERSION.replace(".", r"\.")
EXPECTED_PYPROJECTS = (
    "apps/server/pyproject.toml",
    "packages/builtin-ui/pyproject.toml",
    "packages/control-contracts/pyproject.toml",
    "packages/core/pyproject.toml",
    "packages/module-sdk/pyproject.toml",
    "packages/modules/download-qbittorrent/pyproject.toml",
    "packages/modules/metadata-manual/pyproject.toml",
    "packages/modules/metadata-tmdb/pyproject.toml",
    "packages/modules/release-prowlarr/pyproject.toml",
)
EXPECTED_MANIFESTS = (
    "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/module.toml",
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
    "packages/modules/release-prowlarr/src/media_finder_release_prowlarr/module.toml",
)
EXPECTED_FIXTURES = (
    "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/fixtures/conformance.json",
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/fixtures/conformance.json",
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/fixtures/conformance.json",
    "packages/modules/release-prowlarr/src/media_finder_release_prowlarr/fixtures/conformance.json",
)
# The version the running server reports lives in a production default, so a
# release that leaves it behind publishes a stale build version. It is therefore a
# version-derived surface like any other.
EXPECTED_SERVER_VERSION_MODULE = "apps/server/src/media_finder_server/control_gateway.py"


def _load_preparer() -> ModuleType:
    path = ROOT / "scripts" / "prepare-release.py"
    spec = importlib.util.spec_from_file_location("media_finder_prepare_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        text=True,
        capture_output=True,
        env=environment,
    )


def _tree_digest(root: Path) -> str:
    records = tuple(
        record
        for record in _git(root, "ls-files", "--stage", "-z").stdout.rstrip("\0").split("\0")
        if record
    )
    digest = hashlib.sha256()
    entries: list[tuple[str, str, bytes]] = []
    for record in records:
        metadata, relative = record.split("\t", 1)
        mode = metadata.split(" ", 1)[0]
        entries.append((relative, mode, (root / relative).read_bytes()))
    for relative, mode, content in sorted(entries):
        encoded = relative.encode("utf-8")
        digest.update(encoded)
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _make_fixture_root(path: Path) -> tuple[Path, str]:
    """Create a clean, temporary Git checkout from the approved baseline."""

    path.mkdir()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        tar.extractall(path, filter="data")
    _git(path, "init", "--quiet")
    _git(path, "config", "user.email", "release-tests@example.test")
    _git(path, "config", "user.name", "Release Tests")
    _git(path, "add", ".")
    _git(path, "commit", "--quiet", "-m", "fixture baseline")
    return path, _git(path, "rev-parse", "HEAD").stdout.strip()


def _snapshot(
    root: Path,
    base_commit: str,
    *,
    version: str = NEXT_VERSION,
) -> bytes:
    repository_url = "https://github.com/example/media-finder"
    previous_sha = base_commit
    captured_title = (
        "\u0418\u0441\u043f\u0440\u0430\u0432\u0438\u0442\u044c "
        "\u0432\u044b\u043f\u0443\u0441\u043a \U0001f680"
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "repository": {
            "name": "example/media-finder",
            "url": repository_url,
        },
        "base": {
            "commit": base_commit,
            "tree_sha256": _tree_digest(root),
        },
        "requested_version": version,
        "previous_stable": {
            "tag": PREVIOUS_STABLE_TAG,
            "sha": previous_sha,
            "url": f"{repository_url}/releases/tag/{PREVIOUS_STABLE_TAG}",
        },
        "history": {
            "commits": [
                {
                    "sha": "a" * 40,
                    "url": f"{repository_url}/commit/{'a' * 40}",
                }
            ],
            "pull_requests": [
                {
                    "number": 41,
                    "url": f"{repository_url}/pull/41",
                    "title": captured_title,
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _write_snapshot(tmp_path: Path, content: bytes) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    snapshot = tmp_path / "captured-input.json"
    snapshot.write_bytes(content)
    return snapshot


def _make_lock_tool(
    tmp_path: Path,
    *,
    executable_name: str = "lock-owner.py",
    mutation: str = "none",
) -> tuple[list[str], Path]:
    marker = tmp_path / "lock-owner-called"
    tool = tmp_path / executable_name
    mutation_scripts = {
        "none": "",
        "dependency": (
            "text = text.replace("
            "'    { name = \\\"alembic\\\" },', "
            "'    { name = \\\"uv\\\" },', 1)\n"
        ),
        "wrong-version": (
            f"text = text.replace('version = \\\"{NEXT_VERSION}\\\"', "
            f"'version = \\\"{BASE_VERSION}\\\"', 1)\n"
        ),
        "mode": (
            "readme = pathlib.Path('README.md')\nreadme.chmod(readme.stat().st_mode ^ 0o111)\n"
        ),
        "allowed-mode": (
            f"for relative in ('VERSION', 'uv.lock', 'docs/releases/{NEXT_VERSION}.md'):\n"
            "    target = pathlib.Path(relative)\n"
            "    target.chmod(target.stat().st_mode | 0o111)\n"
        ),
        "record-args": (
            "pathlib.Path(sys.argv[1]).with_name('lock-tool-args').write_text(\n"
            "    '\\n'.join(sys.argv[2:])\n"
            ")\n"
        ),
        "directory": (
            "target = pathlib.Path('README.md')\n"
            "target.unlink()\n"
            "target.mkdir()\n"
            "(target / 'left').write_text('left\\n')\n"
        ),
        "hardlink": (
            "target = pathlib.Path('README.md')\n"
            "target.unlink()\n"
            "target.hardlink_to(pathlib.Path(sys.argv[1]).with_name('outside-secret'))\n"
        ),
    }
    if mutation not in mutation_scripts:
        raise ValueError(f"unknown lock owner mutation: {mutation}")
    tool.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, re, sys\n"
        "if len(sys.argv) > 1 and sys.argv[1].endswith('lock-owner-called'):\n"
        "    pathlib.Path(sys.argv[1]).write_text('called')\n"
        "path = pathlib.Path('uv.lock')\n"
        "text = path.read_text()\n"
        f"text, count = re.subn(r'(?m)^version = \\\"{BASE_VERSION_PATTERN}\\\"$', "
        f"'version = \\\"{NEXT_VERSION}\\\"', text)\n"
        "if count != 9:\n"
        "    raise SystemExit(f'expected nine workspace records, got {count}')\n"
        + mutation_scripts[mutation]
        + "path.write_text(text)\n"
    )
    if executable_name != "lock-owner.py":
        tool.chmod(0o755)
        return [str(tool)], marker
    return [sys.executable, str(tool), str(marker)], marker


def test_canonical_version_validation_rejects_noncanonical_or_prerelease_values() -> None:
    preparer = _load_preparer()

    assert preparer.parse_product_version("1.2.3") == (1, 2, 3)
    for value in ("1.2", "01.2.3", "1.2.3-rc.1", "1.2.3+build.1", "1.2.3;rm", "1.2.3 "):
        with pytest.raises(preparer.PreparationError, match="canonical"):
            preparer.parse_product_version(value)


def test_version_must_increase_beyond_current_and_previous_stable_versions() -> None:
    preparer = _load_preparer()

    for value in ("0.4.0", "0.3.9"):
        with pytest.raises(preparer.PreparationError, match="newer"):
            preparer.validate_requested_version(value, "0.4.0", "v0.4.0")
    with pytest.raises(preparer.PreparationError, match="newer"):
        preparer.validate_requested_version("0.5.0", "0.4.0", "v0.6.0")
    assert preparer.validate_requested_version("0.5.0", "0.4.0", "v0.4.0") == (0, 5, 0)


def test_captured_history_links_are_identity_bound_and_markdown_safe(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    repository_url = "https://github.com/example/media-finder"
    cases = (
        ("history", "commits", {"url": f"{repository_url}/commit/{'b' * 40}"}),
        ("history", "pull_requests", {"url": f"{repository_url}/pull/42"}),
        ("previous_stable", None, {"url": f"{repository_url}/releases/tag/v0.3.0"}),
    )
    for section, entries, replacement in cases:
        payload = json.loads(_snapshot(fixture_root, base_commit))
        if section == "previous_stable":
            payload[section].update(replacement)
        else:
            payload[section][entries][0].update(replacement)
        raw = json.dumps(payload).encode("utf-8")
        with pytest.raises(preparer.PreparationError, match=r"identity|unsafe URL"):
            preparer._parse_snapshot(raw, NEXT_VERSION)


def test_prepare_updates_all_lockstep_surfaces_and_only_allowlisted_files(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, lock_marker = _make_lock_tool(tmp_path)
    before = {
        path: (fixture_root / path).read_bytes()
        for path in _git(fixture_root, "ls-files", "-z").stdout.rstrip("\0").split("\0")
        if path
    }

    result = preparer.prepare_release(
        fixture_root,
        version=NEXT_VERSION,
        snapshot_path=snapshot,
        lock_tool=lock_tool,
    )
    assert lock_marker.read_text() == "called"

    expected_changed = {
        "VERSION",
        *EXPECTED_PYPROJECTS,
        "packages/builtin-ui/package.json",
        *EXPECTED_MANIFESTS,
        *EXPECTED_FIXTURES,
        EXPECTED_SERVER_VERSION_MODULE,
        "uv.lock",
        f"docs/releases/{NEXT_VERSION}.md",
    }
    assert set(result["changed_files"]) == expected_changed
    assert result["version"] == NEXT_VERSION
    assert result["base_commit"] == base_commit
    assert result["candidate_tree_sha256"] != result["base_tree_sha256"]
    assert result["expected_tree"]
    assert all(set(entry) == {"mode", "sha256"} for entry in result["expected_tree"].values())

    current_paths = set(
        path
        for path in _git(fixture_root, "ls-files", "-co", "--exclude-standard", "-z")
        .stdout.rstrip("\0")
        .split("\0")
        if path
    )
    assert current_paths - set(before) == {f"docs/releases/{NEXT_VERSION}.md"}
    assert set(current_paths - set(before)) <= {f"docs/releases/{NEXT_VERSION}.md"}

    import tomllib

    assert (fixture_root / "VERSION").read_text() == f"{NEXT_VERSION}\n"
    assert {
        tomllib.loads((fixture_root / path).read_text())["project"]["version"]
        for path in EXPECTED_PYPROJECTS
    } == {NEXT_VERSION}
    assert (
        json.loads((fixture_root / "packages/builtin-ui/package.json").read_text())["version"]
        == NEXT_VERSION
    )
    assert f'build_version: str = "{NEXT_VERSION}"' in (
        fixture_root / EXPECTED_SERVER_VERSION_MODULE
    ).read_text(encoding="utf-8")
    assert {
        tomllib.loads((fixture_root / path).read_text())["module_version"]
        for path in EXPECTED_MANIFESTS
    } == {NEXT_VERSION}

    locked = tomllib.loads((fixture_root / "uv.lock").read_text())
    assert {
        package["version"]
        for package in locked["package"]
        if package["name"].startswith("media-finder") and package["name"] != "media-finder-tooling"
    } == {NEXT_VERSION}
    for path in EXPECTED_FIXTURES:
        fixture = json.loads((fixture_root / path).read_text())
        manifest_path = fixture_root / path.replace("/fixtures/conformance.json", "/module.toml")
        assert fixture["module_version"] == NEXT_VERSION
        assert fixture["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    for path, content in before.items():
        if path not in expected_changed:
            assert (fixture_root / path).read_bytes() == content


def test_prepare_invokes_owning_lock_tool_without_offline_override(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="record-args")

    preparer.prepare_release(
        fixture_root,
        version=NEXT_VERSION,
        snapshot_path=snapshot,
        lock_tool=lock_tool,
    )

    assert (tmp_path / "lock-tool-args").read_text().splitlines() == ["lock"]


def test_prepare_rejects_a_dirty_or_unexpected_tree_before_mutation(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path)
    (fixture_root / "README.md").write_text("unexpected edit\n")

    with pytest.raises(preparer.PreparationError, match=r"unexpected|dirty"):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )
    assert (fixture_root / "VERSION").read_text() == f"{BASE_VERSION}\n"


def test_prepare_rejects_owner_lock_dependency_mutation_and_restores_candidate(
    tmp_path: Path,
) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="dependency")

    with pytest.raises(preparer.PreparationError, match="changed dependency records"):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )
    assert _git(fixture_root, "status", "--porcelain").stdout == ""
    assert (fixture_root / "VERSION").read_text() == f"{BASE_VERSION}\n"


def test_prepare_rejects_owner_lock_workspace_version_mutation_and_restores_candidate(
    tmp_path: Path,
) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="wrong-version")

    with pytest.raises(
        preparer.PreparationError,
        match="workspace version mismatch after regeneration",
    ):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )
    assert _git(fixture_root, "status", "--porcelain").stdout == ""
    assert (fixture_root / "VERSION").read_text() == f"{BASE_VERSION}\n"


def test_prepare_rejects_directory_replacement_and_restores_tree(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="directory")
    readme = fixture_root / "README.md"
    before_bytes = readme.read_bytes()
    before_mode = readme.stat().st_mode & 0o777

    with pytest.raises(preparer.PreparationError, match="unexpected"):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )

    assert readme.is_file()
    assert readme.read_bytes() == before_bytes
    assert readme.stat().st_mode & 0o777 == before_mode
    assert not (readme / "left").exists()
    assert _git(fixture_root, "status", "--porcelain").stdout == ""


def test_prepare_rejects_outside_hardlink_without_corrupting_sentinel(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="hardlink")
    readme = fixture_root / "README.md"
    outside = tmp_path / "outside-secret"
    outside_bytes = b"outside sentinel\n"
    outside.write_bytes(outside_bytes)
    outside_mode = outside.stat().st_mode & 0o777
    before_bytes = readme.read_bytes()
    before_mode = readme.stat().st_mode & 0o777

    with pytest.raises(preparer.PreparationError, match="unexpected"):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )

    assert outside.read_bytes() == outside_bytes
    assert outside.stat().st_mode & 0o777 == outside_mode
    assert readme.is_file()
    assert readme.read_bytes() == before_bytes
    assert readme.stat().st_mode & 0o777 == before_mode
    assert readme.stat().st_ino != outside.stat().st_ino
    assert _git(fixture_root, "status", "--porcelain").stdout == ""


def test_prepare_rejects_owner_mode_only_tamper_and_restores_mode(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="mode")
    readme = fixture_root / "README.md"
    before_mode = readme.stat().st_mode & 0o777

    with pytest.raises(preparer.PreparationError, match=r"unexpected diff"):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )
    assert readme.stat().st_mode & 0o777 == before_mode
    assert _git(fixture_root, "status", "--porcelain").stdout == ""


def test_prepare_rejects_allowlisted_mode_tamper_and_restores_all_modes(
    tmp_path: Path,
) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    lock_tool, _ = _make_lock_tool(tmp_path, mutation="allowed-mode")
    before_modes = {
        relative: (fixture_root / relative).stat().st_mode & 0o777
        for relative in ("VERSION", "uv.lock")
    }
    notes = fixture_root / f"docs/releases/{NEXT_VERSION}.md"

    with pytest.raises(preparer.PreparationError, match="mode"):
        preparer.prepare_release(
            fixture_root,
            version=NEXT_VERSION,
            snapshot_path=snapshot,
            lock_tool=lock_tool,
        )

    assert {
        relative: (fixture_root / relative).stat().st_mode & 0o777 for relative in before_modes
    } == before_modes
    assert not notes.exists()
    assert _git(fixture_root, "status", "--porcelain").stdout == ""


def test_prepare_is_repeatable_for_the_same_immutable_snapshot(tmp_path: Path) -> None:
    preparer = _load_preparer()
    first_root, first_commit = _make_fixture_root(tmp_path / "first")
    second_root, second_commit = _make_fixture_root(tmp_path / "second")
    first_snapshot = _write_snapshot(
        tmp_path / "first-snapshot", _snapshot(first_root, first_commit)
    )
    second_snapshot = _write_snapshot(
        tmp_path / "second-snapshot", _snapshot(second_root, second_commit)
    )
    lock_tool, _ = _make_lock_tool(tmp_path)

    first = preparer.prepare_release(
        first_root,
        version=NEXT_VERSION,
        snapshot_path=first_snapshot,
        lock_tool=lock_tool,
    )
    second = preparer.prepare_release(
        second_root,
        version=NEXT_VERSION,
        snapshot_path=second_snapshot,
        lock_tool=lock_tool,
    )

    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    assert first["changed_file_sha256"] == second["changed_file_sha256"]
    assert first["candidate_tree_sha256"] == second["candidate_tree_sha256"]
    assert (first_root / first["notes_path"]).read_bytes() == (
        second_root / second["notes_path"]
    ).read_bytes()


def test_notes_are_english_traceable_and_explicitly_unreviewed(tmp_path: Path) -> None:
    preparer = _load_preparer()
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot_bytes = _snapshot(fixture_root, base_commit)
    snapshot = _write_snapshot(tmp_path, snapshot_bytes)
    lock_tool, _ = _make_lock_tool(tmp_path)

    result = preparer.prepare_release(
        fixture_root,
        version=NEXT_VERSION,
        snapshot_path=snapshot,
        lock_tool=lock_tool,
    )
    notes = (fixture_root / result["notes_path"]).read_text()

    assert "Automatically generated from repository history. Not editorially reviewed." in notes
    assert PREVIOUS_STABLE_TAG in notes
    assert f"{PREVIOUS_STABLE_TAG}..{base_commit}" in notes
    assert "https://github.com/example/media-finder/pull/41" in notes
    assert f"https://github.com/example/media-finder/commit/{'a' * 40}" in notes
    assert f"https://github.com/example/media-finder/blob/{base_commit}/docs/operations.md" in notes
    assert "\u0418\u0441\u043f\u0440\u0430\u0432\u0438\u0442\u044c" not in notes
    assert "\U0001f680" not in notes
    assert "## Authored upgrade guidance" not in notes
    assert "No authored upgrade guidance was provided in the captured history." not in notes
    assert "migration" not in notes.casefold()
    assert "compatib" not in notes.casefold()
    assert "rollback" not in notes.casefold()
    assert result["snapshot_sha256"] == hashlib.sha256(snapshot_bytes).hexdigest()
    assert result["snapshot_sha256"] in notes


def test_cli_emits_machine_readable_candidate_result(tmp_path: Path) -> None:
    fixture_root, base_commit = _make_fixture_root(tmp_path / "candidate")
    snapshot = _write_snapshot(tmp_path, _snapshot(fixture_root, base_commit))
    output = tmp_path / "result.json"
    lock_tool, _ = _make_lock_tool(tmp_path, executable_name="uv")

    completed = subprocess.run(
        [
            "python",
            str(ROOT / "scripts" / "prepare-release.py"),
            "--root",
            str(fixture_root),
            "--version",
            NEXT_VERSION,
            "--snapshot",
            str(snapshot),
            "--result",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "PATH": f"{lock_tool[0].rsplit('/', 1)[0]}:{os.environ['PATH']}"},
    )

    result = json.loads(completed.stdout)
    assert json.loads(output.read_text()) == result
    assert result["version"] == NEXT_VERSION
    assert result["notes_path"] == f"docs/releases/{NEXT_VERSION}.md"
