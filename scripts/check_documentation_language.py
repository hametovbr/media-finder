"""Fail when repository documentation contains disallowed Cyrillic prose."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

CYRILLIC = re.compile(r"[\u0400-\u04ff]")
DOCUMENT_SUFFIXES = {".md", ".html", ".py", ".yaml", ".yml"}
ALLOWED_PREFIXES = (
    "src/media_finder/locales/",
    "src/media_finder/ui_i18n.py",
    "tests/",
)


def tracked_documentation() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [
        Path(name)
        for name in result.stdout.splitlines()
        if Path(name).suffix in DOCUMENT_SUFFIXES and not name.startswith(ALLOWED_PREFIXES)
    ]


def main() -> int:
    failures: list[str] = []
    for path in tracked_documentation():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CYRILLIC.search(line):
                failures.append(f"{path.as_posix()}:{line_number}: Cyrillic prose is not allowed")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Documentation language policy passed for {len(tracked_documentation())} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
