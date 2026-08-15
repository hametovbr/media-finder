from pydantic import BaseModel, Field, SecretStr

from media_finder.sdk.conformance import assert_client_conforms, assert_provider_conforms
from media_finder.sdk.settings import describe_settings
from media_finder.sdk.types import ModuleManifest


class Config(BaseModel):
    endpoint: str = Field(title="settings.endpoint", json_schema_extra={"order": 1})
    token: SecretStr = Field(title="settings.token", json_schema_extra={"secret": True, "order": 2})


def test_generic_settings_description_rejects_module_markup() -> None:
    fields = describe_settings(Config)
    assert [field.name for field in fields] == ["endpoint", "token"]
    assert fields[1].secret is True
    assert all(field.html is None and field.javascript is None for field in fields)


def test_module_manifest_rejects_markup_and_paths() -> None:
    manifest = ModuleManifest(
        key="safe", version="1.0.0", contract_version="1", name_key="module.safe"
    )
    assert manifest.key == "safe"


def test_fixture_modules_conform(fake_provider, fake_client) -> None:
    assert_provider_conforms(fake_provider)
    assert_client_conforms(fake_client)
