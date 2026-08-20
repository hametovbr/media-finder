from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from importlib import import_module, metadata, resources
from importlib.resources.abc import Traversable
from pathlib import Path

EXPECTED_DISTRIBUTIONS = {
    "media-finder": "media_finder_server",
    "media-finder-core": "media_finder_core",
    "media-finder-module-sdk": "media_finder_sdk",
    "media-finder-control-contracts": "media_finder_control",
    "media-finder-builtin-ui": "media_finder_builtin_ui",
    "media-finder-metadata-manual": "media_finder_metadata_manual",
    "media-finder-metadata-tmdb": "media_finder_metadata_tmdb",
    "media-finder-release-prowlarr": "media_finder_release_prowlarr",
    "media-finder-download-qbittorrent": "media_finder_download_qbittorrent",
}
RUNTIME_SITE_PACKAGES = Path("/opt/venv/lib/python3.13/site-packages")
FORBIDDEN_SOURCE_PATHS = (Path("/build"), Path("/app/apps"), Path("/app/packages"))
REQUIRED_RESOURCES = frozenset(
    {
        "media_finder_builtin_ui/static/index.html",
        "media_finder_metadata_manual/module.toml",
        "media_finder_metadata_manual/fixtures/conformance.json",
        "media_finder_metadata_tmdb/module.toml",
        "media_finder_metadata_tmdb/fixtures/conformance.json",
        "media_finder_metadata_tmdb/fixtures/movie.json",
        "media_finder_metadata_tmdb/fixtures/season-0.json",
        "media_finder_metadata_tmdb/fixtures/series.json",
        "media_finder_release_prowlarr/module.toml",
        "media_finder_release_prowlarr/fixtures/conformance.json",
        "media_finder_release_prowlarr/fixtures/fixture.torrent",
        "media_finder_release_prowlarr/fixtures/search.json",
        "media_finder_download_qbittorrent/module.toml",
        "media_finder_download_qbittorrent/fixtures/conformance.json",
        "media_finder_core/_migration_resources/alembic.ini",
        "media_finder_core/_migration_resources/alembic/env.py",
        "media_finder_core/_migration_resources/alembic/versions/0001_clean_core.py",
    }
)
REQUIRED_UI_ASSET_PATTERNS = frozenset(
    {
        "media_finder_builtin_ui/static/assets/index-*.css",
        "media_finder_builtin_ui/static/assets/index-*.js",
    }
)
FORBIDDEN_UI_RESOURCE_PREFIXES = (
    "media_finder_builtin_ui/locales/",
    "media_finder_builtin_ui/templates/",
)
FORBIDDEN_UI_RESOURCES = frozenset(
    {
        "media_finder_builtin_ui/static/axe.min.js",
        "media_finder_builtin_ui/static/base.css",
        "media_finder_builtin_ui/static/favicon.svg",
        "media_finder_builtin_ui/static/htmx.min.js",
        "media_finder_builtin_ui/static/manual-editor.js",
        "media_finder_builtin_ui/static/ui.js",
    }
)


class VerificationError(RuntimeError):
    """Raised when the installed production image violates its runtime contract."""


@dataclass(frozen=True)
class DistributionRecord:
    name: str
    version: str
    module_origin: Path
    distribution_origin: Path


@dataclass(frozen=True)
class RuntimeSnapshot:
    distributions: tuple[DistributionRecord, ...]
    existing_forbidden_paths: tuple[Path, ...]
    pth_files: tuple[tuple[Path, str], ...]
    available_resources: frozenset[str]
    migration_head: str | None
    application_processes: tuple[str, ...]


def validate_runtime_snapshot(snapshot: RuntimeSnapshot) -> None:
    expected_names = set(EXPECTED_DISTRIBUTIONS)
    actual_names = {record.name for record in snapshot.distributions}
    missing_names = expected_names - actual_names
    unexpected_names = actual_names - expected_names
    if missing_names:
        raise VerificationError(f"missing distributions: {', '.join(sorted(missing_names))}")
    if unexpected_names or len(snapshot.distributions) != len(EXPECTED_DISTRIBUTIONS):
        raise VerificationError("unexpected or duplicate production distributions")

    runtime_site_packages = RUNTIME_SITE_PACKAGES.resolve()
    for record in snapshot.distributions:
        for origin in (record.module_origin, record.distribution_origin):
            if not origin.resolve().is_relative_to(runtime_site_packages):
                raise VerificationError(
                    f"{record.name} origin is outside runtime site-packages: {origin}"
                )
    versions = {record.version for record in snapshot.distributions}
    if len(versions) != 1:
        raise VerificationError("production distributions do not share one lockstep version")

    if snapshot.existing_forbidden_paths:
        paths = ", ".join(str(path) for path in snapshot.existing_forbidden_paths)
        raise VerificationError(f"forbidden source path exists in runtime image: {paths}")
    for path, contents in snapshot.pth_files:
        if "/build" in contents or "/app/packages" in contents:
            raise VerificationError(f"source path in {path}")

    missing_resources = REQUIRED_RESOURCES - snapshot.available_resources
    if missing_resources:
        raise VerificationError(
            f"missing packaged resources: {', '.join(sorted(missing_resources))}"
        )
    missing_assets = {
        pattern
        for pattern in REQUIRED_UI_ASSET_PATTERNS
        if not any(fnmatchcase(resource, pattern) for resource in snapshot.available_resources)
    }
    if missing_assets:
        raise VerificationError(f"missing packaged UI asset: {', '.join(sorted(missing_assets))}")
    legacy_resources = {
        resource
        for resource in snapshot.available_resources
        if resource in FORBIDDEN_UI_RESOURCES or resource.startswith(FORBIDDEN_UI_RESOURCE_PREFIXES)
    }
    if legacy_resources:
        raise VerificationError(
            f"legacy UI resource remains packaged: {', '.join(sorted(legacy_resources))}"
        )
    if snapshot.migration_head != "0001_clean_core":
        raise VerificationError(f"unexpected migration head: {snapshot.migration_head}")
    if len(snapshot.application_processes) != 1:
        raise VerificationError(
            "production image must have exactly one application process; "
            f"found {len(snapshot.application_processes)}"
        )


def discover_application_processes(proc_root: Path = Path("/proc")) -> tuple[str, ...]:
    processes = []
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            command_line = (process / "cmdline").read_bytes()
        except OSError:
            continue
        if b"-m\x00media_finder_server" in command_line:
            processes.append(process.name)
    return tuple(sorted(processes, key=int))


def discover_package_resources(package_name: str) -> frozenset[str]:
    """Return every packaged file below one importlib resource root."""

    discovered: set[str] = set()

    def visit(node: Traversable, relative: str = "") -> None:
        for child in node.iterdir():
            child_relative = f"{relative}/{child.name}" if relative else child.name
            if child.is_dir():
                visit(child, child_relative)
            elif child.is_file():
                discovered.add(f"{package_name}/{child_relative}")

    visit(resources.files(package_name))
    return frozenset(discovered)


def collect_runtime_snapshot() -> RuntimeSnapshot:
    distributions = []
    for distribution_name, module_name in EXPECTED_DISTRIBUTIONS.items():
        distribution = metadata.distribution(distribution_name)
        module_file = import_module(module_name).__file__
        if module_file is None:
            raise VerificationError(f"{module_name} has no import origin")
        distributions.append(
            DistributionRecord(
                name=distribution_name,
                version=distribution.version,
                module_origin=Path(module_file).resolve(),
                distribution_origin=Path(distribution.locate_file("")).resolve(),
            )
        )

    available_resources = set(discover_package_resources("media_finder_builtin_ui"))
    for resource in REQUIRED_RESOURCES:
        package_name, _, relative_path = resource.partition("/")
        if resources.files(package_name).joinpath(relative_path).is_file():
            available_resources.add(resource)

    from alembic.script import ScriptDirectory
    from media_finder_core.platform.database import _alembic_config

    return RuntimeSnapshot(
        distributions=tuple(distributions),
        existing_forbidden_paths=tuple(path for path in FORBIDDEN_SOURCE_PATHS if path.exists()),
        pth_files=tuple(
            (path, path.read_text(encoding="utf-8")) for path in Path("/opt/venv").rglob("*.pth")
        ),
        available_resources=frozenset(available_resources),
        migration_head=ScriptDirectory.from_config(_alembic_config()).get_current_head(),
        application_processes=discover_application_processes(),
    )


def main() -> int:
    validate_runtime_snapshot(collect_runtime_snapshot())
    print("Production image runtime verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
