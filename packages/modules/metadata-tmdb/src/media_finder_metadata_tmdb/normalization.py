"""TMDB payload normalization into the public metadata schema."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import cast

from media_finder_sdk import (
    Artwork,
    Episode,
    MetadataIdentity,
    ModuleError,
    ModuleFailureCategory,
    NormalizedMetadata,
    Provenance,
    ProviderPayload,
    Rating,
    Season,
)
from pydantic import HttpUrl, ValidationError

_IMAGE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"


def normalize_payload(
    payload: ProviderPayload,
    identity: MetadataIdentity,
    fetched_at: datetime,
) -> NormalizedMetadata:
    try:
        data = payload.data
        if str(data.get("id")) != identity.external_id:
            raise ValueError("identity mismatch")
        title = data.get("title") or data.get("name") or identity.external_id
        release = data.get("release_date") or data.get("first_air_date")
        release_text = release if isinstance(release, str) else None
        seasons = _seasons(data.get("seasons"))
        normalized = NormalizedMetadata(
            kind=identity.media_kind,
            titles={identity.locale: str(title)},
            original_title=_optional_string(
                data.get("original_title") or data.get("original_name")
            ),
            year=int(release_text[:4]) if release_text else None,
            plot=_optional_string(data.get("overview")),
            release_date=date.fromisoformat(release_text) if release_text else None,
            runtime_minutes=_optional_int(data.get("runtime")),
            provider_ids={"tmdb": identity.external_id},
            ratings=_ratings(data),
            genres=_names(data.get("genres")),
            countries=_names(data.get("production_countries")),
            studios=_names(data.get("production_companies")),
            artwork=tuple(
                value
                for value in (
                    _artwork("poster", data.get("poster_path"), identity.locale),
                    _artwork("backdrop", data.get("backdrop_path"), identity.locale),
                )
                if value is not None
            ),
            seasons=seasons,
            provenance=Provenance(
                provider_id="tmdb",
                external_id=identity.external_id,
                locale=identity.locale,
                fetched_at=fetched_at,
                source_label="TMDB",
            ),
            completeness=_completeness(data),
            structural_quality=1.0,
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ModuleError(
            category=ModuleFailureCategory.INVALID_IDENTITY,
            code="metadata_identity_invalid",
        ) from None
    return normalized


def _seasons(value: object) -> tuple[Season, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    seasons: list[Season] = []
    for raw_season in value:
        if not isinstance(raw_season, Mapping):
            continue
        number = _required_int(raw_season.get("season_number"))
        episodes: list[Episode] = []
        raw_episodes = raw_season.get("episodes", ())
        if isinstance(raw_episodes, Sequence) and not isinstance(raw_episodes, str | bytes):
            for raw_episode in raw_episodes:
                if not isinstance(raw_episode, Mapping):
                    continue
                episode_number = _required_int(raw_episode.get("episode_number"))
                episodes.append(
                    Episode(
                        number=episode_number,
                        title=_optional_string(raw_episode.get("name"))
                        or f"Episode {episode_number}",
                        plot=_optional_string(raw_episode.get("overview")),
                        air_date=date.fromisoformat(str(raw_episode["air_date"]))
                        if raw_episode.get("air_date")
                        else None,
                        runtime_minutes=_optional_int(raw_episode.get("runtime")),
                        provider_ids={"tmdb": str(raw_episode["id"])}
                        if raw_episode.get("id") is not None
                        else {},
                        ordering=_optional_int(raw_episode.get("order")) or episode_number,
                    )
                )
        seasons.append(
            Season(
                number=number,
                title=_optional_string(raw_season.get("name")),
                plot=_optional_string(raw_season.get("overview")),
                provider_ids={"tmdb": str(raw_season["id"])}
                if raw_season.get("id") is not None
                else {},
                episodes=tuple(episodes),
            )
        )
    return tuple(seasons)


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(
        str(item["name"]) for item in value if isinstance(item, Mapping) and item.get("name")
    )


def _ratings(data: Mapping[str, object]) -> tuple[Rating, ...]:
    value = data.get("vote_average")
    if value is None:
        return ()
    return (Rating(source="tmdb", value=float(cast(int | float | str, value))),)


def _artwork(kind: str, value: object, locale: str) -> Artwork | None:
    if not isinstance(value, str) or _IMAGE_PATH.fullmatch(value) is None or ".." in value:
        return None
    return Artwork(kind=kind, url=HttpUrl(f"{_IMAGE_BASE_URL}{value}"), language=locale)


def _completeness(data: Mapping[str, object]) -> float:
    present = sum(
        bool(data.get(key))
        for key in ("title", "name", "overview", "release_date", "first_air_date", "runtime")
    )
    return min(1.0, present / 4)


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: object) -> int | None:
    return int(cast(int | str, value)) if value is not None else None


def _required_int(value: object) -> int:
    if value is None:
        raise ValueError("required integer missing")
    return int(cast(int | str, value))


__all__: list[str] = []
