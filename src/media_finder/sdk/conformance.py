"""Small public conformance assertions usable by third-party module fixtures."""

import inspect

from .protocols import DownloadClient, MetadataProvider
from .types import MagnetArtifact, TorrentArtifact

FORBIDDEN_ARGUMENTS = {
    "database",
    "db",
    "session",
    "repository",
    "catalog",
    "jinja",
    "environment",
    "template",
    "template_path",
    "html",
    "javascript",
    "artifact_path",
    "writable_path",
}


def _assert_boundary(module: object) -> None:
    constructor_parameters = set(inspect.signature(type(module)).parameters)
    forbidden_constructor = constructor_parameters & FORBIDDEN_ARGUMENTS
    assert not forbidden_constructor, (
        f"constructor exposes forbidden dependencies: {sorted(forbidden_constructor)}"
    )
    for name, value in vars(module).items():
        type_path = f"{type(value).__module__}.{type(value).__qualname__}".lower()
        assert name not in FORBIDDEN_ARGUMENTS, f"instance stores forbidden dependency: {name}"
        assert not any(
            marker in type_path
            for marker in ("sqlalchemy", "jinja", "media_finder.domain", "media_finder.models")
        ), f"instance stores forbidden application type: {type_path}"
    for name, method in inspect.getmembers(module, predicate=callable):
        if name.startswith("_"):
            continue
        parameters = set(inspect.signature(method).parameters)
        forbidden = parameters & FORBIDDEN_ARGUMENTS
        assert not forbidden, f"{name} exposes forbidden dependencies: {sorted(forbidden)}"


def assert_provider_conforms(provider: MetadataProvider) -> None:
    assert isinstance(provider, MetadataProvider)
    _assert_boundary(provider)
    provider.validate_config()
    assert provider.manifest.contract_version == "1"
    assert provider.attribution().provider_key == provider.manifest.key


def assert_client_conforms(client: DownloadClient) -> None:
    assert isinstance(client, DownloadClient)
    _assert_boundary(client)
    client.validate_config()
    destinations = client.list_destinations()
    assert destinations
    destination = destinations[0].key
    for artifact in (
        MagnetArtifact(uri="magnet:?xt=urn:btih:fixture"),
        TorrentArtifact(content=b"fixture"),
    ):
        result = client.submit(artifact, destination, "mf-acq-fixture")
        assert result.correlation == "mf-acq-fixture"
        assert client.find_by_correlation("mf-acq-fixture").correlation == "mf-acq-fixture"
