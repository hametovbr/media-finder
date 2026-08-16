"""Stable and safe public module failure contract."""

from __future__ import annotations

from typing import cast

import pytest
from media_finder_sdk import ModuleError, ModuleFailureCategory


def test_module_error_has_stable_category_code_and_deeply_immutable_details() -> None:
    error = ModuleError(
        category=ModuleFailureCategory.UNAVAILABLE,
        code="metadata_service_unavailable",
        safe_details={"retryable": True, "upstream": {"status": 503}, "attempts": [1, 2]},
    )

    assert str(error) == "metadata_service_unavailable"
    assert error.safe_details == {
        "retryable": True,
        "upstream": {"status": 503},
        "attempts": (1, 2),
    }
    with pytest.raises(TypeError):
        cast(dict[str, object], error.safe_details)["retryable"] = False
    with pytest.raises(TypeError):
        cast(dict[str, object], error.safe_details["upstream"])["status"] = 200


@pytest.mark.parametrize("code", ("", "Unsafe Code", "contains-secret=value"))
def test_module_error_rejects_unsafe_codes(code: str) -> None:
    with pytest.raises(ValueError, match="module_error_code_invalid"):
        ModuleError(category=ModuleFailureCategory.INVALID_REQUEST, code=code)
