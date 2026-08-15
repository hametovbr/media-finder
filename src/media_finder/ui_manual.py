"""Structured Manual metadata form conversion."""

from __future__ import annotations

import re
from typing import Any

from .sdk.types import NormalizedMetadata

SEASON_FIELD = re.compile(r"^season_(\d+)_number$")
EPISODE_FIELD = re.compile(r"^season_(\d+)_episode_(\d+)_number$")


def structured_manual_document(form: dict[str, str]) -> dict[str, Any]:
    """Convert uniquely indexed browser controls to the public Manual schema-v1 document."""

    kind = form.get("kind", "")
    locale = form.get("metadata_locale", "")
    title = form.get("title", "").strip()
    if kind not in {"movie", "series"} or locale not in {"en", "ru"} or not title:
        raise ValueError("manual_import_invalid")
    document: dict[str, Any] = {
        "schema_version": "1",
        "kind": kind,
        "locale": locale,
        "titles": {locale: title},
    }
    if form.get("external_id"):
        document["external_id"] = form["external_id"]
    for name in ("original_title", "plot", "release_date"):
        if form.get(name, "").strip():
            document[name] = form[name].strip()
    for name in ("year", "runtime_minutes"):
        if form.get(name, "").strip():
            document[name] = int(form[name])
    if kind == "series":
        document["seasons"] = _seasons(form)
    return document


def _seasons(form: dict[str, str]) -> list[dict[str, Any]]:
    seasons: list[dict[str, Any]] = []
    for key in sorted(form):
        match = SEASON_FIELD.fullmatch(key)
        if match is None or not form[key].strip():
            continue
        index = int(match.group(1))
        season: dict[str, Any] = {"number": int(form[key]), "episodes": []}
        title = form.get(f"season_{index}_title", "").strip()
        if title:
            season["title"] = title
        for episode_key in sorted(form):
            episode_match = EPISODE_FIELD.fullmatch(episode_key)
            if episode_match is None or int(episode_match.group(1)) != index:
                continue
            if not form[episode_key].strip():
                continue
            episode_index = int(episode_match.group(2))
            episode_title = form.get(f"season_{index}_episode_{episode_index}_title", "").strip()
            if not episode_title:
                raise ValueError("manual_import_invalid")
            episode: dict[str, Any] = {
                "number": int(form[episode_key]),
                "title": episode_title,
            }
            plot = form.get(f"season_{index}_episode_{episode_index}_plot", "").strip()
            if plot:
                episode["plot"] = plot
            season["episodes"].append(episode)
        seasons.append(season)
    return seasons


def manual_form_view(
    metadata: NormalizedMetadata | None, external_id: str | None = None
) -> dict[str, Any]:
    if metadata is None:
        return {
            "external_id": "",
            "kind": "movie",
            "locale": "en",
            "title": "",
            "original_title": "",
            "year": "",
            "plot": "",
            "release_date": "",
            "runtime_minutes": "",
            "seasons": [
                {
                    "number": 0,
                    "title": "",
                    "episodes": [{"number": 1, "title": "", "plot": ""}],
                }
            ],
        }
    locale = metadata.provenance.locale
    return {
        "external_id": external_id or metadata.provenance.external_id,
        "kind": metadata.kind.value,
        "locale": locale,
        "title": metadata.titles.get(locale) or next(iter(metadata.titles.values())),
        "original_title": metadata.original_title or "",
        "year": metadata.year or "",
        "plot": metadata.plot or "",
        "release_date": metadata.release_date or "",
        "runtime_minutes": metadata.runtime_minutes or "",
        "seasons": [season.model_dump(mode="json") for season in metadata.seasons]
        or [
            {
                "number": 0,
                "title": "",
                "episodes": [{"number": 1, "title": "", "plot": ""}],
            }
        ],
    }
