#!/usr/bin/env python3
"""Prepare a deterministic, lockstep Media Finder release candidate.

The command accepts one captured JSON history snapshot and a canonical product
version.  It only writes the version-derived files owned by this repository and
returns a digest map that a trusted controller can use to compare a later
regeneration.  No snapshot text is interpreted as a command or copied into the
notes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast
from urllib.parse import SplitResult, urlsplit


class PreparationError(RuntimeError):
    """Raised when a release candidate cannot be prepared safely."""


VersionTuple = tuple[int, int, int]

WORKSPACE_PROJECTS: Final[tuple[tuple[str, str], ...]] = (
    ("apps/server/pyproject.toml", "media-finder"),
    ("packages/builtin-ui/pyproject.toml", "media-finder-builtin-ui"),
    ("packages/control-contracts/pyproject.toml", "media-finder-control-contracts"),
    ("packages/core/pyproject.toml", "media-finder-core"),
    ("packages/module-sdk/pyproject.toml", "media-finder-module-sdk"),
    (
        "packages/modules/download-qbittorrent/pyproject.toml",
        "media-finder-download-qbittorrent",
    ),
    ("packages/modules/metadata-manual/pyproject.toml", "media-finder-metadata-manual"),
    ("packages/modules/metadata-tmdb/pyproject.toml", "media-finder-metadata-tmdb"),
    ("packages/modules/release-prowlarr/pyproject.toml", "media-finder-release-prowlarr"),
)
MODULE_MANIFESTS: Final[tuple[str, ...]] = (
    "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/module.toml",
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
    "packages/modules/release-prowlarr/src/media_finder_release_prowlarr/module.toml",
)
CONFORMANCE_FIXTURES: Final[tuple[str, ...]] = (
    "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/fixtures/conformance.json",
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/fixtures/conformance.json",
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/fixtures/conformance.json",
    "packages/modules/release-prowlarr/src/media_finder_release_prowlarr/fixtures/conformance.json",
)
# The version the running server reports is a production default inside the
# composition adapter and nothing else derives it, so a release must rewrite it
# like every other version-bearing surface.
SERVER_VERSION_MODULE: Final[str] = "apps/server/src/media_finder_server/control_gateway.py"
SERVER_VERSION_FIELD: Final[str] = "build_version"
WORKSPACE_NAMES: Final[frozenset[str]] = frozenset(name for _, name in WORKSPACE_PROJECTS)
_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)
_SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_TREE_SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SNAPSHOT_LIMIT = 4 * 1024 * 1024
_DEFAULT_LOCK_TOOL = object()


@dataclass(frozen=True)
class _PreviousStable:
    tag: str
    sha: str
    url: str
    version: VersionTuple


@dataclass(frozen=True)
class _CommitLink:
    sha: str
    url: str


@dataclass(frozen=True)
class _PullRequestLink:
    number: int
    url: str


@dataclass(frozen=True)
class _Snapshot:
    raw: bytes
    sha256: str
    repository_name: str
    repository_url: str
    base_commit: str
    base_tree_sha256: str
    requested_version: str
    previous: _PreviousStable
    commits: tuple[_CommitLink, ...]
    pull_requests: tuple[_PullRequestLink, ...]


def parse_product_version(value: str) -> VersionTuple:
    """Parse the only product-version form accepted by release preparation."""

    if not isinstance(value, str) or _VERSION_PATTERN.fullmatch(value) is None:
        raise PreparationError(
            "version must be canonical X.Y.Z without prerelease or build metadata"
        )
    try:
        components = tuple(int(component) for component in value.split("."))
    except (TypeError, ValueError, OverflowError):
        raise PreparationError(
            "version must be canonical X.Y.Z without prerelease or build metadata"
        ) from None
    if len(components) != 3:
        raise PreparationError(
            "version must be canonical X.Y.Z without prerelease or build metadata"
        )
    return cast(VersionTuple, components)


def _parse_previous_tag(value: str) -> tuple[str, VersionTuple]:
    if not isinstance(value, str) or not value.startswith("v"):
        raise PreparationError("previous stable tag must be canonical vX.Y.Z")
    try:
        version = parse_product_version(value[1:])
    except PreparationError:
        raise PreparationError("previous stable tag must be canonical vX.Y.Z") from None
    return value, version


def validate_requested_version(
    requested: str,
    current: str,
    previous_stable_tag: str,
) -> VersionTuple:
    """Validate canonical input and the two increasing-version boundaries."""

    parsed = parse_product_version(requested)
    current_version = parse_product_version(current)
    _, previous_version = _parse_previous_tag(previous_stable_tag)
    if parsed <= current_version or parsed <= previous_version:
        raise PreparationError(
            "requested version must be newer than the current and previous stable version"
        )
    return parsed


def _as_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PreparationError(f"snapshot {label} must be an object")
    return cast(Mapping[str, object], value)


def _as_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PreparationError(f"snapshot {label} must be a non-empty string")
    return value


def _as_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise PreparationError(f"snapshot {label} must be an array")
    if len(value) > 5000:
        raise PreparationError(f"snapshot {label} exceeds the bounded history limit")
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON value: {value}")


def _validate_url_text(value: str, label: str) -> None:
    if any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or character.isspace()
        or character in '[]()<>`\\"'
        for character in value
    ):
        raise PreparationError(f"snapshot {label} contains unsafe URL text")


def _validate_repository(name: object, url: object) -> tuple[str, str]:
    repository_name = _as_string(name, "repository.name")
    repository_url = _as_string(url, "repository.url")
    _validate_url_text(repository_url, "repository.url")
    if _REPOSITORY_NAME_PATTERN.fullmatch(repository_name) is None:
        raise PreparationError("snapshot repository.name is not a repository identity")
    parsed = _split_url(repository_url, "repository.url")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != f"/{repository_name}"
    ):
        raise PreparationError(
            "snapshot repository.url must be the canonical GitHub repository URL"
        )
    return repository_name, repository_url


def _validate_sha(value: object, label: str) -> str:
    sha = _as_string(value, label)
    if _SHA_PATTERN.fullmatch(sha) is None:
        raise PreparationError(f"snapshot {label} must be a 40- or 64-character lowercase SHA")
    return sha


def _validate_tree_sha(value: object, label: str) -> str:
    sha = _as_string(value, label)
    if _TREE_SHA_PATTERN.fullmatch(sha) is None:
        raise PreparationError(f"snapshot {label} must be a SHA-256 digest")
    return sha


def _split_url(value: str, label: str) -> SplitResult:
    try:
        return urlsplit(value)
    except ValueError as error:
        raise PreparationError(f"snapshot {label} must be a valid HTTPS URL") from error


def _validate_exact_repository_link(
    value: object,
    repository_url: str,
    suffix: str,
    label: str,
) -> str:
    link = _as_string(value, label)
    expected = f"{repository_url}{suffix}"
    if link != expected:
        raise PreparationError(f"snapshot {label} does not match its captured identity")
    return link


def _parse_snapshot(raw: bytes, expected_version: str) -> _Snapshot:
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > _SNAPSHOT_LIMIT:
        raise PreparationError("captured snapshot exceeds the bounded input limit")
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(decoded, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise PreparationError("captured snapshot must be valid UTF-8 JSON") from error
    snapshot = _as_mapping(value, "root")
    schema_version = snapshot.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise PreparationError("snapshot schema_version must be 1")

    repository = _as_mapping(snapshot.get("repository"), "repository")
    repository_name, repository_url = _validate_repository(
        repository.get("name"), repository.get("url")
    )
    base = _as_mapping(snapshot.get("base"), "base")
    base_commit = _validate_sha(base.get("commit"), "base.commit")
    base_tree_sha256 = _validate_tree_sha(base.get("tree_sha256"), "base.tree_sha256")
    requested_version = _as_string(snapshot.get("requested_version"), "requested_version")
    if requested_version != expected_version:
        raise PreparationError("snapshot requested_version does not match --version")

    previous_stable = _as_mapping(snapshot.get("previous_stable"), "previous_stable")
    previous_tag, previous_version = _parse_previous_tag(
        _as_string(previous_stable.get("tag"), "previous_stable.tag")
    )
    previous_sha = _validate_sha(previous_stable.get("sha"), "previous_stable.sha")
    previous_url = _validate_exact_repository_link(
        previous_stable.get("url"),
        repository_url,
        f"/releases/tag/{previous_tag}",
        "previous_stable.url",
    )
    previous = _PreviousStable(
        tag=previous_tag,
        sha=previous_sha,
        url=previous_url,
        version=previous_version,
    )

    history = _as_mapping(snapshot.get("history"), "history")
    commit_values = _as_list(history.get("commits"), "history.commits")
    pull_values = _as_list(history.get("pull_requests"), "history.pull_requests")
    commits: list[_CommitLink] = []
    pull_requests: list[_PullRequestLink] = []

    for index, entry_value in enumerate(commit_values):
        entry = _as_mapping(entry_value, f"history.commits[{index}]")
        sha = _validate_sha(entry.get("sha"), f"history.commits[{index}].sha")
        url = _validate_exact_repository_link(
            entry.get("url"),
            repository_url,
            f"/commit/{sha}",
            f"history.commits[{index}].url",
        )
        commits.append(_CommitLink(sha=sha, url=url))

    for index, entry_value in enumerate(pull_values):
        entry = _as_mapping(entry_value, f"history.pull_requests[{index}]")
        number = entry.get("number")
        if type(number) is not int or number < 1 or number > 1_000_000_000:
            raise PreparationError(f"snapshot history.pull_requests[{index}].number is invalid")
        url = _validate_exact_repository_link(
            entry.get("url"),
            repository_url,
            f"/pull/{number}",
            f"history.pull_requests[{index}].url",
        )
        pull_requests.append(_PullRequestLink(number=number, url=url))

    return _Snapshot(
        raw=raw,
        sha256=digest,
        repository_name=repository_name,
        repository_url=repository_url,
        base_commit=base_commit,
        base_tree_sha256=base_tree_sha256,
        requested_version=requested_version,
        previous=previous,
        commits=tuple(sorted(commits, key=lambda item: (item.sha, item.url))),
        pull_requests=tuple(sorted(pull_requests, key=lambda item: (item.number, item.url))),
    )


def _read_snapshot(path: Path, expected_version: str) -> _Snapshot:
    expanded = path.expanduser()
    resolved = expanded.resolve()
    if expanded.is_symlink() or not resolved.is_file():
        raise PreparationError("captured snapshot must be a regular file")
    try:
        raw = resolved.read_bytes()
    except OSError as error:
        raise PreparationError("captured snapshot could not be read") from error
    return _parse_snapshot(raw, expected_version)


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise PreparationError("git is required for release preparation") from error
    if result.returncode != 0:
        raise PreparationError("release preparation requires a valid Git checkout")
    return result


def _tracked_paths(root: Path) -> tuple[str, ...]:
    result = _git(root, "ls-files", "-z")
    values = tuple(item for item in result.stdout.decode("utf-8").split("\0") if item)
    if not values:
        raise PreparationError("release preparation requires a non-empty Git checkout")
    return tuple(sorted(values))


def _all_candidate_paths(root: Path) -> tuple[str, ...]:
    result = _git(root, "ls-files", "-co", "--exclude-standard", "-z")
    return tuple(sorted(item for item in result.stdout.decode("utf-8").split("\0") if item))


def _assert_clean(root: Path) -> None:
    result = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.stdout:
        raise PreparationError("repository worktree is dirty; unexpected diff would be overwritten")


def _head_commit(root: Path) -> str:
    return _git(root, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode("ascii").strip()


def _tree_digest(files: Mapping[str, tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        encoded = relative.encode("utf-8")
        mode, content = files[relative]
        digest.update(encoded)
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str, *, create_parents: bool = False) -> Path:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in {".", ".."} for part in parts):
        raise PreparationError(f"rollback path escapes the checkout: {relative}")
    current = root
    for part in parts[:-1]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if not create_parents:
                return root.joinpath(*parts)
            try:
                current.mkdir()
            except OSError as error:
                raise PreparationError(
                    f"rollback parent could not be created: {relative}"
                ) from error
            continue
        except OSError as error:
            raise PreparationError(f"rollback parent could not be inspected: {relative}") from error
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not create_parents:
            raise PreparationError(f"candidate path has a non-directory parent: {relative}")
        _remove_path(current)
        try:
            current.mkdir()
        except OSError as error:
            raise PreparationError(f"rollback parent could not be created: {relative}") from error
    return root.joinpath(*parts)


def _tree_files(root: Path, paths: Sequence[str]) -> dict[str, tuple[str, bytes]]:
    files: dict[str, tuple[str, bytes]] = {}
    for relative in paths:
        path = _safe_path(root, relative)
        try:
            info = os.lstat(path)
        except OSError as error:
            raise PreparationError(f"tracked path could not be read: {relative}") from error
        if not stat.S_ISREG(info.st_mode):
            raise PreparationError(f"tracked path is not a regular file: {relative}")
        try:
            mode = "100755" if info.st_mode & 0o111 else "100644"
            files[relative] = (mode, path.read_bytes())
        except OSError as error:
            raise PreparationError(f"tracked path could not be read: {relative}") from error
    return files


def _read_required_file(root: Path, relative: str) -> bytes:
    try:
        return (root / relative).read_bytes()
    except OSError as error:
        raise PreparationError(f"required release file could not be read: {relative}") from error


def _assignment_bytes(content: bytes, field: str, old_value: str, new_value: str) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PreparationError(f"{field} owner file is not UTF-8") from error
    pattern = re.compile(
        rf"^(?P<prefix>[ \t]*{re.escape(field)}[ \t]*=[ \t]*\")"
        rf"(?P<value>{re.escape(old_value)})"
        rf"(?P<suffix>\"[ \t]*)$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise PreparationError(f"{field} must have exactly one canonical assignment")
    match = matches[0]
    return (text[: match.start("value")] + new_value + text[match.end("value") :]).encode("utf-8")


def _annotated_default_bytes(content: bytes, field: str, old_value: str, new_value: str) -> bytes:
    """Rewrite one annotated-and-assigned string default in a Python module."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PreparationError(f"{field} owner file is not UTF-8") from error
    pattern = re.compile(
        rf"^(?P<prefix>[ \t]*{re.escape(field)}[ \t]*:[ \t]*str[ \t]*=[ \t]*\")"
        rf"(?P<value>{re.escape(old_value)})"
        rf"(?P<suffix>\"[ \t]*,?[ \t]*)$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise PreparationError(f"{field} must have exactly one canonical annotated default")
    match = matches[0]
    return (text[: match.start("value")] + new_value + text[match.end("value") :]).encode("utf-8")


def _json_object(content: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(content.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise PreparationError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise PreparationError(f"{label} must contain a JSON object")
    return cast(dict[str, object], value)


def _json_assignment_bytes(content: bytes, field: str, old_value: str, new_value: str) -> bytes:
    _json_object(content, field)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PreparationError(f"{field} is not UTF-8") from error
    pattern = re.compile(
        rf'^(?P<prefix>[ \t]*"{re.escape(field)}"[ \t]*:[ \t]*")'
        rf"(?P<value>{re.escape(old_value)})"
        rf'(?P<suffix>"[ \t]*,?[ \t]*)$',
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise PreparationError(f"JSON {field} must have exactly one canonical assignment")
    match = matches[0]
    return (text[: match.start("value")] + new_value + text[match.end("value") :]).encode("utf-8")


def _project_dependencies(project: Mapping[str, object]) -> object:
    return (
        project.get("dependencies"),
        project.get("optional-dependencies"),
        project.get("requires-python"),
    )


def _project_data(root: Path, relative: str, expected_name: str) -> tuple[dict[str, object], bytes]:
    path = root / relative
    try:
        content = path.read_bytes()
        value = tomllib.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PreparationError(f"workspace metadata is invalid: {relative}") from error
    project = _as_mapping(value.get("project"), f"{relative}.project")
    if project.get("name") != expected_name:
        raise PreparationError(f"workspace metadata package name mismatch: {relative}")
    version = project.get("version")
    if not isinstance(version, str):
        raise PreparationError(f"workspace metadata version missing: {relative}")
    return dict(project), content


def _lock_package_records(value: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, dict) or not isinstance(value.get("package"), list):
        raise PreparationError("uv.lock package records are missing")
    records: dict[str, Mapping[str, object]] = {}
    for record_value in value["package"]:
        record = _as_mapping(record_value, "uv.lock.package")
        name = record.get("name")
        if isinstance(name, str):
            if name in records:
                raise PreparationError(f"uv.lock contains duplicate package record: {name}")
            records[name] = record
    return records


def _lock_projection(value: object) -> object:
    if not isinstance(value, dict):
        return value
    copied: dict[str, object] = {}
    for key, item in value.items():
        if key == "package" and isinstance(item, list):
            packages: list[object] = []
            for package_value in item:
                if isinstance(package_value, dict) and package_value.get("name") in WORKSPACE_NAMES:
                    package = dict(package_value)
                    package.pop("version", None)
                    packages.append(package)
                else:
                    packages.append(package_value)
            copied[key] = packages
        else:
            copied[key] = item
    return copied


def _module_data(root: Path, relative: str, current: str) -> tuple[bytes, bytes]:
    path = root / relative
    try:
        original = path.read_bytes()
        parsed = tomllib.loads(original.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PreparationError(f"module manifest is invalid: {relative}") from error
    if parsed.get("module_version") != current:
        raise PreparationError(f"module manifest version mismatch: {relative}")
    updated = _assignment_bytes(original, "module_version", current, "__RELEASE_VERSION__")
    return original, updated


def _fixture_bytes(
    original: bytes,
    manifest_before: bytes,
    manifest_after: bytes,
    current: str,
    requested: str,
    label: str,
) -> bytes:
    fixture = _json_object(original, label)
    if fixture.get("module_version") != current:
        raise PreparationError(f"serialized conformance version mismatch: {label}")
    expected_hash = hashlib.sha256(manifest_before).hexdigest()
    if fixture.get("manifest_sha256") != expected_hash:
        raise PreparationError(f"serialized conformance manifest hash mismatch: {label}")
    updated = _json_assignment_bytes(original, "module_version", current, requested)
    updated = _json_assignment_bytes(
        updated,
        "manifest_sha256",
        expected_hash,
        hashlib.sha256(manifest_after).hexdigest(),
    )
    _json_object(updated, label)
    return updated


def _build_notes(snapshot: _Snapshot, version: str) -> bytes:
    previous = snapshot.previous
    range_label = f"{previous.tag}..{snapshot.base_commit}"
    compare_url = f"{snapshot.repository_url}/compare/{previous.tag}...{snapshot.base_commit}"
    lines = [
        f"# Media Finder {version}",
        "",
        "Automatically generated from repository history. Not editorially reviewed.",
        "",
        f"Previous stable release: [{previous.tag}]({previous.url}).",
        f"Previous stable commit: `{previous.sha}`.",
        f"Candidate history range: [`{range_label}`]({compare_url}).",
        "",
        "## Included commits",
        "",
    ]
    if snapshot.commits:
        lines.extend(f"- Commit [`{item.sha}`]({item.url})." for item in snapshot.commits)
    else:
        lines.append("- No commit links were captured.")
    lines.extend(["", "## Included pull requests", ""])
    if snapshot.pull_requests:
        lines.extend(
            f"- Pull request [#{item.number}]({item.url})." for item in snapshot.pull_requests
        )
    else:
        lines.append("- No pull request links were captured.")
    operator_documentation = (
        "See the [upgrade and backup guidance]("
        f"{snapshot.repository_url}/blob/{snapshot.base_commit}/docs/operations.md)."
    )
    lines.extend(
        [
            "",
            "## Operator documentation",
            "",
            operator_documentation,
            "",
            f"Captured input snapshot: `{snapshot.sha256}`.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _resolve_lock_tool(root: Path, lock_tool: object) -> list[str] | None:
    if lock_tool is None:
        raise PreparationError("owning uv lock regeneration is required")
    if lock_tool is not _DEFAULT_LOCK_TOOL:
        if isinstance(lock_tool, (str, Path)):
            return [str(lock_tool)]
        if isinstance(lock_tool, Sequence) and not isinstance(lock_tool, (str, bytes)):
            values = [str(item) for item in lock_tool]
            if values:
                return values
        raise PreparationError("lock_tool must be a non-empty command sequence")
    pinned = root / ".venv" / "bin" / "uv"
    if pinned.is_file() and os.access(pinned, os.X_OK):
        return [str(pinned)]
    discovered = shutil.which("uv")
    if discovered is None:
        raise PreparationError("pinned uv is required for lock regeneration")
    return [discovered]


def _run_lock_tool(root: Path, command: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            [*command, "lock"],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise PreparationError("owning uv lock regeneration could not start") from error
    if completed.returncode != 0:
        raise PreparationError(
            f"owning uv lock regeneration failed with exit code {completed.returncode}"
        )


def _write_file(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            os.fchmod(handle.fileno(), mode)
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        raise PreparationError(f"could not write release candidate file: {path}") from error


def _remove_path(path: Path) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise PreparationError(f"rollback path could not be inspected: {path}") from error
    try:
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as error:
        raise PreparationError(f"rollback path could not be removed: {path}") from error


def _restore_file(root: Path, relative: str, mode: str, content: bytes) -> None:
    path = _safe_path(root, relative, create_parents=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            os.fchmod(handle.fileno(), int(mode, 8) & 0o777)
        try:
            os.replace(temporary, path)
        except IsADirectoryError:
            _remove_path(path)
            os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise PreparationError(f"rollback file could not be restored: {relative}") from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _restore_files(
    root: Path,
    before: Mapping[str, tuple[str, bytes]],
    paths: Sequence[str],
) -> None:
    unexpected_paths = sorted(
        (relative for relative in paths if relative not in before),
        key=lambda value: (len(Path(value).parts), value),
    )
    for relative in unexpected_paths:
        _remove_path(_safe_path(root, relative, create_parents=True))
    for relative in sorted(before, key=lambda value: (-len(Path(value).parts), value)):
        mode, content = before[relative]
        _restore_file(root, relative, mode, content)

    restored_paths = _all_candidate_paths(root)
    if set(restored_paths) != set(before):
        unexpected = sorted(set(restored_paths) ^ set(before))
        raise PreparationError("rollback left unexpected files: " + ", ".join(unexpected))
    restored = _tree_files(root, restored_paths)
    for relative, expected in before.items():
        if restored.get(relative) != expected:
            raise PreparationError(f"rollback output mismatch: {relative}")


def _verify_candidate(
    root: Path,
    before: Mapping[str, tuple[str, bytes]],
    expected_contents: Mapping[str, bytes],
    allowed_paths: frozenset[str],
    base_tree_sha256: str,
    dependency_projection: object,
    project_dependencies: Mapping[str, object],
    requested_version: str,
) -> tuple[dict[str, tuple[str, bytes]], tuple[str, ...]]:
    after_paths = _all_candidate_paths(root)
    expected_paths = set(before) | set(expected_contents)
    if set(after_paths) != expected_paths:
        unexpected = sorted(set(after_paths) ^ expected_paths)
        raise PreparationError("candidate contains unexpected files: " + ", ".join(unexpected))
    after = _tree_files(root, after_paths)
    changed = tuple(
        sorted(relative for relative in expected_paths if before.get(relative) != after[relative])
    )
    if set(changed) - allowed_paths:
        unexpected = ", ".join(sorted(set(changed) - allowed_paths))
        raise PreparationError("candidate contains unexpected diff: " + unexpected)
    if not set(changed) <= allowed_paths:
        raise PreparationError("candidate changed a path outside the release allowlist")
    for relative, (mode, _content) in after.items():
        expected_mode = before.get(relative, ("100644", b""))[0]
        if mode != expected_mode:
            raise PreparationError(f"candidate mode mismatch: {relative}")
    for relative, expected in expected_contents.items():
        if after.get(relative, ("", b""))[1] != expected and relative != "uv.lock":
            raise PreparationError(f"candidate output mismatch: {relative}")
    try:
        lock_value = tomllib.loads(after["uv.lock"][1].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PreparationError("candidate uv.lock is invalid") from error
    if _lock_projection(lock_value) != dependency_projection:
        raise PreparationError("candidate uv.lock changed dependency records")
    lock_records = _lock_package_records(lock_value)
    for name in WORKSPACE_NAMES:
        if lock_records.get(name, {}).get("version") != requested_version:
            raise PreparationError(f"uv.lock workspace version mismatch after regeneration: {name}")
    for relative, expected in project_dependencies.items():
        try:
            value = tomllib.loads(after[relative][1].decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise PreparationError(
                f"workspace metadata is invalid after regeneration: {relative}"
            ) from error
        project = _as_mapping(value.get("project"), f"{relative}.project")
        if _project_dependencies(project) != expected:
            raise PreparationError(f"workspace dependency records changed: {relative}")
    if _tree_digest(after) == base_tree_sha256:
        raise PreparationError("candidate tree did not change")
    return after, changed


def prepare_release(
    root: Path,
    *,
    version: str,
    snapshot_path: Path,
    lock_tool: object = _DEFAULT_LOCK_TOOL,
) -> dict[str, object]:
    """Generate one candidate in a clean Git checkout."""

    if not isinstance(root, Path):
        root = Path(root)
    if not isinstance(snapshot_path, Path):
        snapshot_path = Path(snapshot_path)
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise PreparationError("repository root must be a directory")
    parse_product_version(version)
    _assert_clean(root)
    tracked = _tracked_paths(root)
    before = _tree_files(root, tracked)
    base_tree_sha256 = _tree_digest(before)
    snapshot = _read_snapshot(snapshot_path, version)
    if snapshot.base_tree_sha256 != base_tree_sha256:
        raise PreparationError("captured base tree does not match the checkout")
    if _head_commit(root) != snapshot.base_commit:
        raise PreparationError("captured base commit does not match the checkout")

    version_path = root / "VERSION"
    try:
        current_bytes = version_path.read_bytes()
        current = current_bytes.decode("utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise PreparationError("root VERSION is unreadable") from error
    if current_bytes != f"{current}\n".encode():
        raise PreparationError("root VERSION must contain one canonical line")
    validate_requested_version(version, current, snapshot.previous.tag)

    expected_contents: dict[str, bytes] = {"VERSION": f"{version}\n".encode()}
    project_dependencies: dict[str, object] = {}
    for relative, name in WORKSPACE_PROJECTS:
        project, original = _project_data(root, relative, name)
        if project.get("version") != current:
            raise PreparationError(f"workspace version mismatch: {relative}")
        project_dependencies[relative] = _project_dependencies(project)
        expected_contents[relative] = _assignment_bytes(original, "version", current, version)

    ui_relative = "packages/builtin-ui/package.json"
    ui_original = _read_required_file(root, ui_relative)
    ui_value = _json_object(ui_original, ui_relative)
    if ui_value.get("version") != current:
        raise PreparationError(f"UI package version mismatch: {ui_relative}")
    expected_contents[ui_relative] = _json_assignment_bytes(
        ui_original, "version", current, version
    )

    manifest_before: dict[str, bytes] = {}
    manifest_after: dict[str, bytes] = {}
    for relative in MODULE_MANIFESTS:
        original, updated = _module_data(root, relative, current)
        manifest_before[relative] = original
        manifest_after[relative] = updated.replace(b"__RELEASE_VERSION__", version.encode("utf-8"))
        expected_contents[relative] = manifest_after[relative]

    for fixture_relative, manifest_relative in zip(
        CONFORMANCE_FIXTURES,
        MODULE_MANIFESTS,
        strict=True,
    ):
        original = _read_required_file(root, fixture_relative)
        expected_contents[fixture_relative] = _fixture_bytes(
            original,
            manifest_before[manifest_relative],
            manifest_after[manifest_relative],
            current,
            version,
            fixture_relative,
        )

    server_version_original = _read_required_file(root, SERVER_VERSION_MODULE)
    expected_contents[SERVER_VERSION_MODULE] = _annotated_default_bytes(
        server_version_original,
        SERVER_VERSION_FIELD,
        current,
        version,
    )

    lock_relative = "uv.lock"
    lock_original = _read_required_file(root, lock_relative)
    try:
        lock_before_value = tomllib.loads(lock_original.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PreparationError("uv.lock is invalid") from error
    # Validate every workspace record before changing any bytes.
    lock_records = _lock_package_records(lock_before_value)
    for name in WORKSPACE_NAMES:
        record = lock_records.get(name)
        if record is None or record.get("version") != current:
            raise PreparationError(f"uv.lock workspace version mismatch: {name}")
    dependency_projection = _lock_projection(lock_before_value)
    # uv.lock is generated by the owning uv tool after all project metadata has
    # been written; retaining its baseline bytes here keeps it in the exact
    # allowlist without hand-editing generated output.
    expected_contents[lock_relative] = lock_original

    notes_relative = f"docs/releases/{version}.md"
    notes = _build_notes(snapshot, version)
    if notes_relative in before and before[notes_relative][1] != notes:
        raise PreparationError("existing release notes differ from the captured candidate inputs")
    expected_contents[notes_relative] = notes

    allowed_paths = frozenset(expected_contents)
    command = _resolve_lock_tool(root, lock_tool)
    write_paths = tuple(sorted(expected_contents))
    try:
        for relative, content in expected_contents.items():
            if before.get(relative, ("", b""))[1] != content:
                _write_file(root / relative, content)
        if command is not None:
            _run_lock_tool(root, command)
        after, changed = _verify_candidate(
            root,
            before,
            expected_contents,
            allowed_paths,
            base_tree_sha256,
            dependency_projection,
            project_dependencies,
            version,
        )
    except PreparationError as error:
        try:
            current_paths = _all_candidate_paths(root)
            restore_paths = set(before) | set(write_paths) | set(current_paths)
            expected_paths = set(before) | set(write_paths)
            for relative in current_paths:
                parts = Path(relative).parts
                for index in range(1, len(parts)):
                    parent = "/".join(parts[:index])
                    if parent in expected_paths or any(
                        expected.startswith(f"{parent}/") for expected in expected_paths
                    ):
                        continue
                    restore_paths.add(parent)
            _restore_files(root, before, tuple(restore_paths))
        except PreparationError as restore_error:
            raise PreparationError(f"{error}; rollback failed: {restore_error}") from restore_error
        raise
    candidate_tree_sha256 = _tree_digest(after)
    changed_file_sha256 = {
        relative: hashlib.sha256(after[relative][1]).hexdigest() for relative in changed
    }
    expected_tree = {
        relative: {"mode": mode, "sha256": hashlib.sha256(content).hexdigest()}
        for relative, (mode, content) in after.items()
    }
    return {
        "schema_version": 1,
        "version": version,
        "base_commit": snapshot.base_commit,
        "previous_stable_tag": snapshot.previous.tag,
        "previous_stable_sha": snapshot.previous.sha,
        "snapshot_sha256": snapshot.sha256,
        "base_tree_sha256": base_tree_sha256,
        "candidate_tree_sha256": candidate_tree_sha256,
        "notes_path": notes_relative,
        "workspace_packages": sorted(WORKSPACE_NAMES),
        "changed_files": list(changed),
        "changed_file_sha256": changed_file_sha256,
        "expected_tree": expected_tree,
    }


def _validate_result_path(path: Path, root: Path) -> Path:
    expanded = path.expanduser()
    resolved = expanded.resolve()
    if resolved.is_relative_to(root):
        raise PreparationError("result output must be outside the candidate checkout")
    if expanded.is_symlink():
        raise PreparationError("result output must not be a symlink")
    if expanded.exists() and not expanded.is_file():
        raise PreparationError("result output must be a regular file")
    return resolved


def _write_result(path: Path, result: Mapping[str, object], root: Path) -> None:
    resolved = _validate_result_path(path, root)
    serialized = (
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    )
    _write_file(resolved, serialized)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="clean Git checkout to prepare"
    )
    parser.add_argument("--version", required=True, help="canonical stable product version X.Y.Z")
    parser.add_argument(
        "--snapshot",
        dest="snapshot",
        type=Path,
        required=True,
        help="immutable captured history snapshot JSON",
    )
    parser.add_argument(
        "--result",
        dest="result",
        type=Path,
        help="optional machine-readable result path outside --root",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = args.root.expanduser().resolve()
        result_path = None
        if args.result is not None:
            result_path = _validate_result_path(args.result, root)
            if result_path == args.snapshot.expanduser().resolve():
                raise PreparationError("result output must differ from the input snapshot")
        result = prepare_release(
            root,
            version=args.version,
            snapshot_path=args.snapshot,
        )
        output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        print(output)
        if result_path is not None:
            _write_result(result_path, result, root)
    except PreparationError as error:
        print(f"prepare-release: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
