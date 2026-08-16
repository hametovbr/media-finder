"""Compile the checked gettext catalogs deterministically with locked Babel."""

from __future__ import annotations

import argparse
import io
import sys
import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

ROOT = Path(__file__).parents[1]
DEFAULT_CATALOG_ROOT = (
    ROOT / "packages" / "builtin-ui" / "src" / "media_finder_builtin_ui" / "locales"
)
SUPPORTED_LOCALES = ("en", "ru")


def assert_locked_babel(lockfile: Path = ROOT / "uv.lock") -> None:
    """Reject catalog compilation by a Babel version other than the locked one."""
    lock = tomllib.loads(lockfile.read_text(encoding="utf-8"))
    locked_version = next(
        (str(package["version"]) for package in lock["package"] if package["name"] == "babel"),
        None,
    )
    if locked_version is None:
        raise RuntimeError("babel_missing_from_uv_lock")
    if distribution_version("babel") != locked_version:
        raise RuntimeError("babel_version_does_not_match_uv_lock")


def compiled_catalog(source: Path, *, locale: str) -> bytes:
    """Return the deterministic GNU MO representation of one PO catalog."""
    with source.open("rb") as stream:
        catalog = read_po(stream, locale=locale)
    output = io.BytesIO()
    write_mo(output, catalog, use_fuzzy=False)
    return output.getvalue()


def build_catalogs(catalog_root: Path, *, check: bool) -> tuple[Path, ...]:
    """Build catalogs or return every checked file whose bytes have drifted."""
    drift: list[Path] = []
    for locale in SUPPORTED_LOCALES:
        directory = catalog_root / locale / "LC_MESSAGES"
        source = directory / "messages.po"
        target = directory / "messages.mo"
        expected = compiled_catalog(source, locale=locale)
        actual = target.read_bytes() if target.is_file() else None
        if actual == expected:
            continue
        if check:
            drift.append(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected)
    return tuple(drift)


def main() -> int:
    assert_locked_babel()
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT)
    arguments = parser.parse_args()
    drift = build_catalogs(arguments.catalog_root.resolve(), check=arguments.check)
    if drift:
        for path in drift:
            print(f"compiled locale drift: {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
