import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

_CHECKER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "check_documentation_language.py")
)
violations_for = cast(Callable[[Path, str], list[str]], _CHECKER["violations_for"])


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (Path("tests/test_domain.py"), "# Недопустимый комментарий\n"),
        (Path("assets-src/ui.js"), "// Недопустимый текст\n"),
        (Path("pyproject.toml"), 'description = "Недопустимый текст"\n'),
        (Path("package.json"), '{"description": "Недопустимый текст"}\n'),
    ],
)
def test_developer_facing_cyrillic_is_rejected(path: Path, content: str) -> None:
    assert violations_for(path, content) == [f"{path.as_posix()}:1: Cyrillic prose is not allowed"]


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (
            Path(
                "packages/builtin-ui/src/media_finder_builtin_ui/locales/ru/LC_MESSAGES/messages.po"
            ),
            'msgstr "Разрешённый перевод"\n',
        ),
        (
            Path(
                "packages/modules/metadata-manual/src/"
                "media_finder_metadata_manual/translations/ru.json"
            ),
            '{"module.manual.name": "Вручную"}\n',
        ),
        (Path("tests/test_ui_i18n.py"), 'expected = "Разрешённый перевод"\n'),
        (
            Path("packages/builtin-ui/tests/test_browser.py"),
            'expected = "Разрешённый перевод"\n',
        ),
        (
            Path("packages/builtin-ui/tests/test_fake_gateway.py"),
            'expected = "Разрешённый перевод"\n',
        ),
        (
            Path("packages/builtin-ui/tests/test_html_contract.py"),
            'expected = "Разрешённый перевод"\n',
        ),
        (Path("tests/test_naming.py"), 'title = "Пользовательский тайтл"\n'),
        (
            Path("tests/fixtures/user_metadata/manual.json"),
            '{"title": "Пользовательский тайтл"}\n',
        ),
    ],
)
def test_localization_and_user_metadata_values_are_allowed(path: Path, content: str) -> None:
    assert violations_for(path, content) == []


def test_localization_test_comment_is_still_developer_prose() -> None:
    path = Path("tests/test_ui_i18n.py")

    assert violations_for(path, "# Недопустимый комментарий\n") == [
        "tests/test_ui_i18n.py:1: Cyrillic prose is not allowed"
    ]
