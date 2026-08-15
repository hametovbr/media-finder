"""Structured Manual form conversion over public control contracts."""

from __future__ import annotations

import re
from typing import Any

from media_finder_control import Locale, ManualDocumentV1, MediaKind
from media_finder_control.models import MetadataView

SEASON_FIELD = re.compile(r"^season_(\d+)_number$")
EPISODE_FIELD = re.compile(r"^season_(\d+)_episode_(\d+)_number$")


def editable_document(
    metadata: MetadataView,
    *,
    external_id: str,
    locale: Locale,
) -> ManualDocumentV1:
    return ManualDocumentV1(
        schema_version="1",
        external_id=external_id,
        locale=locale,
        **metadata.model_dump(mode="json"),
    )


def structured_document(
    form: dict[str, str],
    current: ManualDocumentV1 | None = None,
) -> ManualDocumentV1:
    try:
        kind = MediaKind(form.get("kind", ""))
        locale = Locale(form.get("metadata_locale", ""))
    except ValueError:
        raise ValueError("manual_import_invalid") from None
    title = form.get("title", "").strip()
    if not title:
        raise ValueError("manual_import_invalid")
    payload: dict[str, Any] = current.model_dump(mode="json") if current else {}
    titles = dict(current.titles) if current else {}
    titles[locale.value] = title
    payload.update(
        {
            "schema_version": "1",
            "external_id": form.get("external_id") or None,
            "kind": kind,
            "locale": locale,
            "titles": titles,
            "original_title": form.get("original_title") or None,
            "plot": form.get("plot") or None,
            "release_date": form.get("release_date") or None,
            "year": int(form["year"]) if form.get("year") else None,
            "runtime_minutes": (
                int(form["runtime_minutes"]) if form.get("runtime_minutes") else None
            ),
            "seasons": _seasons(form, current) if kind is MediaKind.SERIES else [],
        }
    )
    return ManualDocumentV1.model_validate(payload)


def _seasons(form: dict[str, str], current: ManualDocumentV1 | None) -> list[dict[str, Any]]:
    existing = (
        {season.number: season.model_dump(mode="json") for season in current.seasons}
        if current
        else {}
    )
    seasons: list[dict[str, Any]] = []
    for key in sorted(form):
        match = SEASON_FIELD.fullmatch(key)
        if match is None or not form[key].strip():
            continue
        index = int(match.group(1))
        source = form.get(f"season_{index}_source_number", "")
        season = dict(existing.get(int(source), {})) if source else {}
        old_episodes = {episode["number"]: episode for episode in season.get("episodes", [])}
        season.update(
            {
                "number": int(form[key]),
                "title": form.get(f"season_{index}_title") or None,
                "episodes": [],
            }
        )
        for episode_key in sorted(form):
            episode_match = EPISODE_FIELD.fullmatch(episode_key)
            if episode_match is None or int(episode_match.group(1)) != index:
                continue
            episode_index = int(episode_match.group(2))
            title = form.get(f"season_{index}_episode_{episode_index}_title", "").strip()
            if not title:
                raise ValueError("manual_import_invalid")
            source_episode = form.get(f"season_{index}_episode_{episode_index}_source_number", "")
            episode = dict(old_episodes.get(int(source_episode), {})) if source_episode else {}
            episode.update(
                {
                    "number": int(form[episode_key]),
                    "title": title,
                    "plot": form.get(f"season_{index}_episode_{episode_index}_plot") or None,
                }
            )
            season["episodes"].append(episode)
        seasons.append(season)
    return seasons


def form_view(
    document: ManualDocumentV1 | None,
    preferred_locale: Locale,
    *,
    item_id: str = "",
) -> dict[str, Any]:
    if document is None:
        return {
            "external_id": "",
            "item_id": "",
            "kind": "movie",
            "locale": preferred_locale.value,
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
    locale = preferred_locale.value
    payload = document.model_dump(mode="json")
    payload.update(
        {
            "item_id": item_id,
            "locale": locale,
            "title": document.titles.get(locale) or next(iter(document.titles.values())),
            "original_title": document.original_title or "",
            "year": document.year or "",
            "plot": document.plot or "",
            "release_date": document.release_date or "",
            "runtime_minutes": document.runtime_minutes or "",
            "seasons": [
                {
                    **season.model_dump(mode="json"),
                    "source_number": season.number,
                    "episodes": [
                        {**episode.model_dump(mode="json"), "source_number": episode.number}
                        for episode in season.episodes
                    ],
                }
                for season in document.seasons
            ],
        }
    )
    return payload
