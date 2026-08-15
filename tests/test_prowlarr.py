from datetime import UTC, datetime, timedelta

import pytest
from media_finder_sdk import (
    MagnetArtifact,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    TorrentArtifact,
)

from media_finder.release_selection import (
    ReleaseSelectionCache,
    ReleaseSelectionExpired,
    ReleaseSelectionService,
)


class FixtureReleaseProvider:
    def __init__(self) -> None:
        self.resolved: list[bytes] = []
        self.closed = False

    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title=f"{query.query}.Release",
                    indexer="Fixture Indexer",
                    guid="fixture-guid",
                    infohash="a" * 40,
                    source_page_url="https://indexer.example.test/releases/fixture",
                ),
                selection=PrivateReleaseSelection.from_bytes(f"private:{query.query}".encode()),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection):
        payload = selection.payload()
        self.resolved.append(payload)
        if payload == b"private:torrent":
            return TorrentArtifact.from_bytes(b"fixture torrent bytes")
        return MagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40)

    def close(self) -> None:
        self.closed = True


def test_release_selection_exposes_only_safe_snapshot_and_resolves_private_selection() -> None:
    provider = FixtureReleaseProvider()
    service = ReleaseSelectionService(provider, ReleaseSelectionCache())

    selected = service.search(ReleaseSearchQuery(query="Fixture"))[0]

    assert selected.snapshot == SafeReleaseSnapshot(
        title="Fixture.Release",
        indexer="Fixture Indexer",
        guid="fixture-guid",
        infohash="a" * 40,
        source_page_url="https://indexer.example.test/releases/fixture",
    )
    assert not hasattr(selected, "selection")
    assert "private" not in selected.token

    resolved = service.resolve(selected.token)

    assert resolved.snapshot == selected.snapshot
    assert resolved.artifact == MagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40)
    assert provider.resolved == [b"private:Fixture"]
    with pytest.raises(ReleaseSelectionExpired):
        service.resolve(selected.token)


def test_release_selection_cache_enforces_ttl_lru_eviction_and_process_locality() -> None:
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    provider = FixtureReleaseProvider()
    cache = ReleaseSelectionCache(
        ttl=timedelta(seconds=30),
        max_entries=2,
        clock=lambda: current[0],
    )
    service = ReleaseSelectionService(provider, cache)

    first = service.search(ReleaseSearchQuery(query="first"))[0]
    second = service.search(ReleaseSearchQuery(query="second"))[0]
    assert service.inspect(first.token).title == "first.Release"
    third = service.search(ReleaseSearchQuery(query="third"))[0]

    with pytest.raises(ReleaseSelectionExpired):
        service.inspect(second.token)
    assert service.inspect(first.token).title == "first.Release"
    assert service.inspect(third.token).title == "third.Release"

    restarted = ReleaseSelectionService(
        provider,
        ReleaseSelectionCache(clock=lambda: current[0]),
    )
    with pytest.raises(ReleaseSelectionExpired):
        restarted.inspect(first.token)

    current[0] += timedelta(seconds=31)
    with pytest.raises(ReleaseSelectionExpired):
        service.inspect(third.token)


def test_release_selection_resolves_torrent_bytes_in_memory_and_closes_provider() -> None:
    provider = FixtureReleaseProvider()
    service = ReleaseSelectionService(provider, ReleaseSelectionCache())
    selected = service.search(ReleaseSearchQuery(query="torrent"))[0]

    resolved = service.resolve(selected.token)
    service.close()

    assert isinstance(resolved.artifact, TorrentArtifact)
    assert resolved.artifact.content() == b"fixture torrent bytes"
    assert provider.closed is True
