"""Shared SDK foundation fixtures."""

from __future__ import annotations

from media_finder_sdk import ModuleKind


def manifest_toml(
    *,
    module_id: str = "example-metadata",
    module_kind: ModuleKind = ModuleKind.METADATA_PROVIDER,
    module_version: str = "1.2.3",
    sdk_compatibility: str = ">=1,<2",
    contract_version: str = "1",
    capabilities: tuple[str, ...] = ("search", "fetch", "normalize"),
    environment: str = "",
) -> bytes:
    quoted_capabilities = ", ".join(f'"{value}"' for value in capabilities)
    return f'''\
module_id = "{module_id}"
module_kind = "{module_kind.value}"
module_version = "{module_version}"
sdk_compatibility = "{sdk_compatibility}"
contract_version = "{contract_version}"
name_key = "module.example.name"
capabilities = [{quoted_capabilities}]
translation_keys = ["module.example.name", "module.example.token", "module.example.notice"]

[attribution]
notice_key = "module.example.notice"
url = "https://example.test/credits"

{environment}'''.encode()
