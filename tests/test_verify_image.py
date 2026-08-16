from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_verifier() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "verify-image.py"
    spec = importlib.util.spec_from_file_location("media_finder_verify_image", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_snapshot(verifier: ModuleType) -> object:
    site_packages = Path("/opt/venv/lib/python3.13/site-packages")
    distributions = tuple(
        verifier.DistributionRecord(
            name=name,
            version="0.1.0",
            module_origin=site_packages / module_name / "__init__.py",
            distribution_origin=site_packages / f"{name.replace('-', '_')}-0.1.0.dist-info",
        )
        for name, module_name in verifier.EXPECTED_DISTRIBUTIONS.items()
    )
    return verifier.RuntimeSnapshot(
        distributions=distributions,
        existing_forbidden_paths=(),
        pth_files=(),
        available_resources=verifier.REQUIRED_RESOURCES,
        migration_head="0001_clean_core",
        application_processes=("1",),
    )


def test_runtime_snapshot_accepts_all_wheel_only_image_invariants() -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)

    verifier.validate_runtime_snapshot(snapshot)


def test_runtime_snapshot_requires_all_nine_distributions() -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    assert len(snapshot.distributions) == 9
    incomplete = verifier.RuntimeSnapshot(
        **{**vars(snapshot), "distributions": snapshot.distributions[:-1]}
    )

    with pytest.raises(verifier.VerificationError, match="missing distributions"):
        verifier.validate_runtime_snapshot(incomplete)


@pytest.mark.parametrize("origin_field", ["module_origin", "distribution_origin"])
def test_runtime_snapshot_rejects_distribution_origins_outside_runtime_venv(
    origin_field: str,
) -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    first = snapshot.distributions[0]
    replacement = verifier.DistributionRecord(
        **{**vars(first), origin_field: Path("/build") / origin_field}
    )
    invalid = verifier.RuntimeSnapshot(
        **{**vars(snapshot), "distributions": (replacement, *snapshot.distributions[1:])}
    )

    with pytest.raises(verifier.VerificationError, match="outside runtime site-packages"):
        verifier.validate_runtime_snapshot(invalid)


def test_runtime_snapshot_requires_one_lockstep_product_version() -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    first = snapshot.distributions[0]
    replacement = verifier.DistributionRecord(**{**vars(first), "version": "9.9.9"})
    invalid = verifier.RuntimeSnapshot(
        **{**vars(snapshot), "distributions": (replacement, *snapshot.distributions[1:])}
    )

    with pytest.raises(verifier.VerificationError, match="lockstep version"):
        verifier.validate_runtime_snapshot(invalid)


@pytest.mark.parametrize(
    ("existing_paths", "pth_files", "expected"),
    [
        ((Path("/build"),), (), "forbidden source path"),
        ((), ((Path("editable.pth"), "/app/packages/core/src"),), "source path in editable.pth"),
    ],
)
def test_runtime_snapshot_rejects_source_tree_leakage(
    existing_paths: tuple[Path, ...],
    pth_files: tuple[tuple[Path, str], ...],
    expected: str,
) -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    invalid = verifier.RuntimeSnapshot(
        **{
            **vars(snapshot),
            "existing_forbidden_paths": existing_paths,
            "pth_files": pth_files,
        }
    )

    with pytest.raises(verifier.VerificationError, match=expected):
        verifier.validate_runtime_snapshot(invalid)


def test_runtime_snapshot_requires_every_packaged_resource() -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    missing = "media_finder_core/_migration_resources/alembic/versions/0001_clean_core.py"
    invalid = verifier.RuntimeSnapshot(
        **{
            **vars(snapshot),
            "available_resources": snapshot.available_resources - {missing},
        }
    )

    with pytest.raises(verifier.VerificationError, match="missing packaged resources"):
        verifier.validate_runtime_snapshot(invalid)


def test_runtime_snapshot_requires_clean_core_migration_head() -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    invalid = verifier.RuntimeSnapshot(**{**vars(snapshot), "migration_head": "legacy"})

    with pytest.raises(verifier.VerificationError, match="migration head"):
        verifier.validate_runtime_snapshot(invalid)


@pytest.mark.parametrize("processes", [(), ("1", "2")])
def test_runtime_snapshot_requires_exactly_one_application_process(
    processes: tuple[str, ...],
) -> None:
    verifier = _load_verifier()
    snapshot = _valid_snapshot(verifier)
    invalid = verifier.RuntimeSnapshot(**{**vars(snapshot), "application_processes": processes})

    with pytest.raises(verifier.VerificationError, match="exactly one application process"):
        verifier.validate_runtime_snapshot(invalid)


def test_process_discovery_reads_only_media_finder_server_commands(tmp_path: Path) -> None:
    verifier = _load_verifier()
    for process_id, command in {
        "1": b"python\x00-m\x00media_finder_server\x00",
        "2": b"python\x00worker.py\x00",
        "not-a-pid": b"python\x00-m\x00media_finder_server\x00",
    }.items():
        process = tmp_path / process_id
        process.mkdir()
        (process / "cmdline").write_bytes(command)

    assert verifier.discover_application_processes(tmp_path) == ("1",)
