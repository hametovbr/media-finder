from datetime import UTC, datetime, timedelta

import pytest
from media_finder_core.platform import EphemeralCache, EphemeralTokenExpired


def test_cache_tokens_are_opaque_bounded_and_expire_with_fake_clock() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    cache = EphemeralCache[str](ttl=timedelta(seconds=10), max_entries=2, clock=lambda: now)

    first = cache.put("first")
    second = cache.put("second")
    third = cache.put("third")

    assert len(first) >= 32 and "first" not in first
    with pytest.raises(EphemeralTokenExpired):
        cache.get(first)
    assert cache.get(second) == "second"
    assert cache.pop(third) == "third"
    with pytest.raises(EphemeralTokenExpired):
        cache.pop(third)

    expiring = cache.put("expiring")
    now += timedelta(seconds=10)
    with pytest.raises(EphemeralTokenExpired):
        cache.get(expiring)


def test_new_cache_invalidates_tokens_from_prior_process_instance() -> None:
    first = EphemeralCache[str]()
    token = first.put("draft")

    with pytest.raises(EphemeralTokenExpired):
        EphemeralCache[str]().get(token)
