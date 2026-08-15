from pydantic import BaseModel, Field, SecretStr

from media_finder.modules.manual import ManualProvider
from media_finder.modules.tmdb import TmdbConfig, TmdbProvider
from media_finder.sdk.conformance import assert_client_conforms, assert_provider_conforms
from media_finder.sdk.settings import describe_settings
from media_finder.sdk.types import ModuleManifest, PublicModel


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


class RealProviderTransport:
    def get_json(self, path: str, params: dict[str, str]) -> dict:
        return (
            {"results": []}
            if path.startswith("/search/")
            else {"id": 1, "title": "Fixture", "release_date": "2024-01-01"}
        )


def test_real_metadata_providers_conform_without_application_dependencies() -> None:
    assert_provider_conforms(ManualProvider())
    assert_provider_conforms(
        TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), RealProviderTransport())
    )


def test_public_models_never_contain_raw_provider_payload_fields() -> None:
    pending = list(PublicModel.__subclasses__())
    seen: set[type[PublicModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        pending.extend(model.__subclasses__())
        forbidden = {
            name
            for name in model.model_fields
            if name in {"raw_payload", "provider_payload"} or name.startswith("raw_provider")
        }
        assert not forbidden, f"{model.__name__} exposes {sorted(forbidden)}"
