"""Structured Jellyfin/Kodi NFO projection."""

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .naming import EntityType, render_naming
from .sdk.types import Episode, NormalizedMetadata, Season


@dataclass(frozen=True, slots=True)
class NfoResult:
    xml: str
    filename: str


def render_nfo(
    metadata: NormalizedMetadata,
    *,
    entity_type: EntityType,
    season_number: int | None = None,
    episode_numbers: tuple[int, ...] = (),
) -> NfoResult:
    if entity_type is EntityType.MOVIE:
        if metadata.kind.value != "movie":
            raise ValueError("nfo_entity_mismatch")
        _no_selectors(season_number, episode_numbers)
        root = ET.Element("movie")
        _media_fields(root, metadata)
    elif entity_type is EntityType.TVSHOW:
        if metadata.kind.value != "series":
            raise ValueError("nfo_entity_mismatch")
        _no_selectors(season_number, episode_numbers)
        root = ET.Element("tvshow")
        _media_fields(root, metadata)
    elif entity_type is EntityType.SEASON:
        if metadata.kind.value != "series":
            raise ValueError("nfo_entity_mismatch")
        if season_number is None or episode_numbers:
            raise ValueError("nfo_selector_invalid")
        season = _season(metadata, season_number)
        root = ET.Element("season")
        _text(root, "title", season.title)
        _text(root, "plot", season.plot)
        _text(root, "seasonnumber", season.number)
        _provider_ids(root, season.provider_ids, metadata.provenance.provider_key)
    else:
        if metadata.kind.value != "series":
            raise ValueError("nfo_entity_mismatch")
        if season_number is None or not episode_numbers:
            raise ValueError("nfo_selector_invalid")
        if len(set(episode_numbers)) != 1:
            raise ValueError("nfo_multi_episode_unsupported")
        season = _season(metadata, season_number)
        episode = _episode(season, episode_numbers[0])
        root = ET.Element("episodedetails")
        _text(root, "title", episode.title)
        _text(root, "showtitle", _title(metadata))
        _text(root, "plot", episode.plot)
        _text(root, "aired", episode.air_date)
        _text(root, "runtime", episode.runtime_minutes)
        _text(root, "season", season.number)
        _text(root, "episode", episode.number)
        _text(root, "displayepisode", episode.ordering)
        _provider_ids(root, episode.provider_ids, metadata.provenance.provider_key)

    filename = render_naming(
        metadata,
        entity_type=entity_type,
        season_number=season_number,
        episode_numbers=episode_numbers,
    ).nfo_filename
    return NfoResult(ET.tostring(root, encoding="unicode"), filename)


def _media_fields(root: ET.Element, metadata: NormalizedMetadata) -> None:
    _text(root, "title", _title(metadata))
    _text(root, "originaltitle", metadata.original_title)
    _text(root, "plot", metadata.plot)
    _text(root, "year", metadata.year)
    _text(root, "premiered", metadata.release_date)
    _text(root, "runtime", metadata.runtime_minutes)
    _provider_ids(root, metadata.provider_ids, metadata.provenance.provider_key)
    if metadata.ratings:
        ratings = ET.SubElement(root, "ratings")
        for rating in metadata.ratings:
            node = ET.SubElement(ratings, "rating", name=rating.source)
            _text(node, "value", rating.value)
            _text(node, "votes", rating.votes)
    for name, values in (
        ("genre", metadata.genres),
        ("tag", metadata.tags),
        ("country", metadata.countries),
        ("studio", metadata.studios),
    ):
        for value in values:
            _text(root, name, value)
    for person in metadata.people:
        role = person.role.casefold()
        if role == "director":
            _text(root, "director", person.name)
        elif role in {"writer", "credits"}:
            _text(root, "credits", person.name)
        else:
            actor = ET.SubElement(root, "actor")
            _text(actor, "name", person.name)
            _text(actor, "role", person.character or person.role)
    for artwork in metadata.artwork:
        attributes = {"aspect": artwork.kind}
        if artwork.language is not None:
            attributes["lang"] = artwork.language
        node = ET.SubElement(root, "thumb", attributes)
        node.text = str(artwork.url)


def _provider_ids(root: ET.Element, values: dict[str, str], default_provider: str) -> None:
    for provider, value in sorted(values.items()):
        node = ET.SubElement(
            root,
            "uniqueid",
            type=provider,
            default="true" if provider == default_provider else "false",
        )
        node.text = value


def _text(root: ET.Element, name: str, value: object | None) -> None:
    if value is None:
        return
    ET.SubElement(root, name).text = str(value)


def _title(metadata: NormalizedMetadata) -> str:
    return metadata.titles.get(metadata.provenance.locale) or next(iter(metadata.titles.values()))


def _no_selectors(season_number: int | None, episode_numbers: tuple[int, ...]) -> None:
    if season_number is not None or episode_numbers:
        raise ValueError("nfo_selector_invalid")


def _season(metadata: NormalizedMetadata, number: int) -> Season:
    for season in metadata.seasons:
        if season.number == number:
            return season
    raise ValueError("nfo_selector_invalid")


def _episode(season: Season, number: int) -> Episode:
    for episode in season.episodes:
        if episode.number == number:
            return episode
    raise ValueError("nfo_selector_invalid")
