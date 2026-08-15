"""Fixed, extension-independent Jellyfin naming contract."""

import re
import unicodedata
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .sdk.types import NormalizedMetadata, Season

EXTENSION = re.compile(r"^[A-Za-z0-9]{1,10}$")
RESERVED_CHARACTERS = frozenset('<>:"/\\|?*')
WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


class EntityType(StrEnum):
    MOVIE = "movie"
    TVSHOW = "tvshow"
    SEASON = "season"
    EPISODE = "episode"


class NamingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: str
    relative_directory: str
    basename: str
    target_extension: str | None
    relative_path: str
    nfo_filename: str


def render_naming(
    metadata: NormalizedMetadata,
    *,
    entity_type: EntityType,
    season_number: int | None = None,
    episode_numbers: tuple[int, ...] = (),
    target_extension: str | None = None,
    profile: str = "jellyfin-v1",
) -> NamingResult:
    if profile != "jellyfin-v1":
        raise ValueError("naming_profile_unsupported")
    extension = _extension(target_extension)
    title = _component(_title(metadata))
    root = _component(f"{title} ({metadata.year})" if metadata.year is not None else title)

    if entity_type is EntityType.MOVIE:
        if metadata.kind.value != "movie":
            raise ValueError("naming_entity_mismatch")
        _reject_selectors(season_number, episode_numbers)
        directory, basename, nfo = root, root, f"{root}.nfo"
    else:
        if metadata.kind.value != "series":
            raise ValueError("naming_entity_mismatch")
        if entity_type is EntityType.TVSHOW:
            _reject_selectors(season_number, episode_numbers)
            directory, basename, nfo = root, root, "tvshow.nfo"
        elif entity_type is EntityType.SEASON:
            if season_number is None or episode_numbers:
                raise ValueError("naming_selector_invalid")
            _season(metadata, season_number)
            season_name = f"Season {season_number:02d}"
            directory, basename, nfo = f"{root}/{season_name}", season_name, "season.nfo"
        else:
            if season_number is None or not episode_numbers:
                raise ValueError("naming_selector_invalid")
            season = _season(metadata, season_number)
            numbers = tuple(sorted(set(episode_numbers)))
            if any(number < 1 for number in numbers):
                raise ValueError("naming_selector_invalid")
            episodes = {episode.number: episode for episode in season.episodes}
            if any(number not in episodes for number in numbers):
                raise ValueError("naming_selector_invalid")
            selector = f"S{season_number:02d}E{numbers[0]:02d}"
            if len(numbers) > 1:
                selector += f"-E{numbers[-1]:02d}"
            episode_title = (
                f" - {_component(episodes[numbers[0]].title)}" if len(numbers) == 1 else ""
            )
            season_name = f"Season {season_number:02d}"
            directory = f"{root}/{season_name}"
            basename = _component(f"{title} - {selector}{episode_title}")
            nfo = f"{basename}.nfo"

    relative_path = f"{directory}/{basename}"
    if extension is not None:
        relative_path += f".{extension}"
    return NamingResult(
        profile=profile,
        relative_directory=directory,
        basename=basename,
        target_extension=extension,
        relative_path=relative_path,
        nfo_filename=nfo,
    )


def _extension(value: str | None) -> str | None:
    if value is None:
        return None
    if not EXTENSION.fullmatch(value):
        raise ValueError("target_extension_invalid")
    return value.casefold()


def _title(metadata: NormalizedMetadata) -> str:
    locale = metadata.provenance.locale
    return metadata.titles.get(locale) or next(iter(metadata.titles.values()))


def _component(value: str) -> str:
    cleaned = "".join(
        " "
        if character in RESERVED_CHARACTERS or unicodedata.category(character).startswith("C")
        else character
        for character in value
    )
    cleaned = cleaned.replace("..", " ")
    cleaned = " ".join(cleaned.split()).strip(" .")
    if not cleaned:
        return "_"
    if cleaned.casefold() in WINDOWS_RESERVED:
        return f"_{cleaned}"
    return cleaned


def _reject_selectors(season_number: int | None, episode_numbers: tuple[int, ...]) -> None:
    if season_number is not None or episode_numbers:
        raise ValueError("naming_selector_invalid")


def _season(metadata: NormalizedMetadata, number: int) -> Season:
    for season in metadata.seasons:
        if season.number == number:
            return season
    raise ValueError("naming_selector_invalid")
