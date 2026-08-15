import asyncio
import json
from typing import cast

from media_finder_control import ReadinessStatus
from media_finder_server import create_legacy_module_registry, create_runtime_factory
from sqlalchemy.orm import Session, sessionmaker

from media_finder.control_gateway import BackendControlGateway
from media_finder.integration_runtime import RuntimeResolver, RuntimeResult
from media_finder.system_clients import ensure_system_qbittorrent

REGISTRY = create_legacy_module_registry()
RELEASE_INTEGRATION = create_runtime_factory(environment={}).release_integration


class DiagnosticRuntime:
    def __init__(self, provider, client) -> None:
        self.provider = provider
        self.client = client
        self.set_names = {
            "TMDB_TOKEN",
            "QBITTORRENT_URL",
            "QBITTORRENT_USERNAME",
            "QBITTORRENT_PASSWORD",
        }

    @property
    def supported_providers(self):
        return {"manual": self.provider, "tmdb": self.provider}

    def metadata_provider(self, key: str):
        if key == "manual":
            return RuntimeResult(self.provider)
        return RuntimeResult(None, "metadata_provider_unavailable")

    def metadata_providers(self):
        return {"manual": self.provider}

    def configured_provider_attributions(self):
        return [self.provider.attribution()]

    def prowlarr(self):
        return RuntimeResult(None, "integration_environment_missing")

    def download_client(self, instance):
        return RuntimeResult(self.client)

    def environment_is_set(self, name: str) -> bool:
        return name in self.set_names


def test_diagnostics_publish_only_declarations_and_safe_states(
    database: Session, fake_provider, fake_client
) -> None:
    ensure_system_qbittorrent(database)
    gateway = BackendControlGateway(
        sessions=sessionmaker(bind=database.get_bind(), expire_on_commit=False),
        cursor_secret=b"cursor-secret-for-tests",
        runtime=cast(RuntimeResolver, DiagnosticRuntime(fake_provider, fake_client)),
        registry=REGISTRY,
        release_integration=RELEASE_INTEGRATION,
        build_version="1.2.3",
    )

    async def scenario() -> None:
        diagnostics = await gateway.integration_diagnostics()
        by_key = {entry.key: entry for entry in diagnostics}
        assert by_key["manual"].status is ReadinessStatus.READY
        assert by_key["tmdb"].status is ReadinessStatus.UNAVAILABLE
        assert by_key["prowlarr"].status is ReadinessStatus.MISSING
        assert by_key["qbittorrent"].status is ReadinessStatus.READY
        tmdb_token = by_key["tmdb"].variables[0]
        assert tmdb_token.name == "TMDB_TOKEN"
        assert tmdb_token.secret is True
        assert tmdb_token.is_set is True

        serialized = json.dumps([entry.model_dump(mode="json") for entry in diagnostics])
        assert "super-secret-token" not in serialized
        assert "value" not in serialized
        assert "hash" not in serialized

        providers = await gateway.metadata_providers()
        assert {provider.key for provider in providers} == {"manual", "tmdb"}
        about = await gateway.about()
        assert about.version == "1.2.3"
        assert about.attributions[0].provider_key == fake_provider.manifest.key

    asyncio.run(scenario())
