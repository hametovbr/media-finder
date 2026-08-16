import asyncio
import json

from gateway_fixtures import create_gateway
from media_finder_control import ReadinessStatus
from sqlalchemy.orm import Session


def test_diagnostics_publish_only_declarations_and_safe_states(
    database: Session, fake_provider, fake_client
) -> None:
    gateway = create_gateway(
        database,
        metadata_provider=fake_provider,
        download_client=fake_client,
        build_version="1.2.3",
    )

    async def scenario() -> None:
        diagnostics = await gateway.integration_diagnostics()
        by_key = {entry.key: entry for entry in diagnostics}
        assert by_key["manual"].status is ReadinessStatus.READY
        assert by_key["fixture-provider"].status is ReadinessStatus.READY
        assert by_key["fixture-release"].status is ReadinessStatus.UNAVAILABLE
        assert by_key["fixture-download"].status is ReadinessStatus.READY

        serialized = json.dumps([entry.model_dump(mode="json") for entry in diagnostics])
        assert "super-secret-token" not in serialized
        assert '"value"' not in serialized
        assert '"hash"' not in serialized

        providers = await gateway.metadata_providers()
        assert {provider.key for provider in providers} == {"manual", "fixture-provider"}
        about = await gateway.about()
        assert about.version == "1.2.3"

    asyncio.run(scenario())
