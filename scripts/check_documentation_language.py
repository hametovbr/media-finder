"""Fail when developer-facing repository prose contains Cyrillic text."""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

CYRILLIC = re.compile(r"[\u0400-\u04ff]")
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".mako",
    ".po",
    ".ps1",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {".dockerignore", "Dockerfile", "LICENSE"}
LOCALIZATION_TESTS = {
    "tests/test_documentation_language.py",
    "tests/test_naming.py",
    "tests/test_nfo.py",
    "tests/test_ui_browser.py",
    "tests/test_builtin_ui_fake_host.py",
    "tests/test_ui_catalog.py",
    "tests/test_ui_error_feedback.py",
    "tests/test_ui_foundation.py",
    "tests/test_ui_i18n.py",
    "tests/test_ui_manual_structured.py",
    "tests/test_ui_release_live_clients.py",
    "tests/test_ui_release_acceptance.py",
}
MODULE_TRANSLATION = re.compile(
    r"^(src/media_finder/modules/[^/]+/translations|"
    r"packages/modules/[^/]+/src/[^/]+/translations|"
    r"packages/builtin-ui/src/media_finder_builtin_ui/module_translations/[^/]+)/ru\.json$"
)

Position = tuple[int, int]
Span = tuple[Position, Position]


def _contains(span: Span, position: Position) -> bool:
    return span[0] <= position < span[1]


def _python_string_spans(content: str) -> tuple[list[Span], list[Span]]:
    strings = [
        (token.start, token.end)
        for token in tokenize.generate_tokens(io.StringIO(content).readline)
        if token.type == tokenize.STRING
    ]
    docstrings: list[Span] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return strings, docstrings
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not body or not isinstance(body, list):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
            and first.end_col_offset is not None
        ):
            docstrings.append(
                (
                    (first.lineno, first.col_offset),
                    (first.end_lineno, first.end_col_offset),
                )
            )
    return strings, docstrings


def _is_catalog_or_user_fixture(path: Path) -> bool:
    normalized = path.as_posix()
    return (
        normalized.startswith("packages/builtin-ui/src/media_finder_builtin_ui/locales/")
        or MODULE_TRANSLATION.fullmatch(normalized) is not None
        or normalized.startswith("tests/fixtures/user_metadata/")
    )


def violations_for(path: Path, content: str) -> list[str]:
    """Return precise policy violations for one repository-relative text file."""

    normalized = path.as_posix()
    if _is_catalog_or_user_fixture(path):
        return []
    allowed_strings: list[Span] = []
    docstrings: list[Span] = []
    if normalized in LOCALIZATION_TESTS and path.suffix == ".py":
        allowed_strings, docstrings = _python_string_spans(content)

    violations: list[str] = []
    for line_number, line in enumerate(content.splitlines(), 1):
        rejected = False
        for match in CYRILLIC.finditer(line):
            position = (line_number, match.start())
            in_allowed_value = any(_contains(span, position) for span in allowed_strings)
            in_docstring = any(_contains(span, position) for span in docstrings)
            if not in_allowed_value or in_docstring:
                rejected = True
                break
        if rejected:
            violations.append(f"{normalized}:{line_number}: Cyrillic prose is not allowed")
    return violations


def tracked_text_files() -> list[Path]:
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
        if Path(name).exists()
        and (Path(name).suffix in TEXT_SUFFIXES or Path(name).name in TEXT_FILENAMES)
    ]


def main() -> int:
    paths = tracked_text_files()
    failures: list[str] = []
    for path in paths:
        failures.extend(violations_for(path, path.read_text(encoding="utf-8")))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Documentation language policy passed for {len(paths)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
