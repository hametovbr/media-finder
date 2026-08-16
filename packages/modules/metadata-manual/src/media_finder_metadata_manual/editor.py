"""Provider-owned Manual import and episode-table semantics."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from uuid import uuid4

from media_finder_sdk import (
    Episode,
    EpisodeTableDocument,
    MediaKind,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    NormalizedMetadata,
    ProviderPayload,
    Season,
)
from pydantic import ValidationError

from .document import ManualDocumentV1
from .provider import invalid_manual_input


class ManualEditor:
    def import_document(self, document: MetadataImportDocument) -> MetadataEditResult:
        try:
            decoded = json.loads(document.content().decode("utf-8"))
            parsed = ManualDocumentV1.model_validate(decoded)
            identity = MetadataIdentity(
                provider_id="manual",
                external_id=parsed.external_id or str(uuid4()),
                media_kind=parsed.kind,
                locale=parsed.locale,
            )
            return MetadataEditResult(
                identity=identity,
                raw_payload=ProviderPayload(data=decoded),
                metadata=parsed.normalized(identity),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
            TypeError,
        ):
            raise invalid_manual_input() from None

    def merge_episode_table(
        self,
        current: NormalizedMetadata,
        document: EpisodeTableDocument,
    ) -> MetadataEditResult:
        try:
            if current.kind is not MediaKind.SERIES:
                raise ValueError("manual_episode_table_requires_series")
            content = document.content().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content, newline=""))
            required = {"season", "episode", "title"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError("manual_episode_table_columns_invalid")
            rows = list(reader)
            if not rows:
                raise ValueError("manual_episode_table_empty")
            additions: dict[int, list[Episode]] = {}
            for row in rows:
                season_number = int(self._required(row, "season"))
                episode_number = int(self._required(row, "episode"))
                title = self._required(row, "title").strip()
                if season_number < 0 or episode_number < 1 or not title:
                    raise ValueError("manual_episode_table_coordinates_invalid")
                additions.setdefault(season_number, []).append(
                    Episode(
                        number=episode_number,
                        title=title,
                        plot=self._optional(row, "plot"),
                        air_date=self._optional_date(row, "air_date"),
                        runtime_minutes=self._optional_int(row, "runtime_minutes"),
                    )
                )
            seasons = {season.number: season for season in current.seasons}
            for number, episodes in additions.items():
                previous = seasons.get(number, Season(number=number))
                seasons[number] = previous.model_copy(
                    update={"episodes": previous.episodes + tuple(episodes)}
                )
            updated = current.model_copy(
                update={"seasons": tuple(seasons[number] for number in sorted(seasons))}
            )
            provenance = current.provenance
            identity = MetadataIdentity(
                provider_id=provenance.provider_id,
                external_id=provenance.external_id,
                media_kind=current.kind,
                locale=provenance.locale,
            )
            return MetadataEditResult(
                identity=identity,
                raw_payload=ProviderPayload(data={"episode_table": content}),
                metadata=updated,
            )
        except (
            UnicodeDecodeError,
            csv.Error,
            ValidationError,
            ValueError,
            TypeError,
            KeyError,
        ):
            raise invalid_manual_input() from None

    def close(self) -> None:
        return None

    @staticmethod
    def _required(row: dict[str, str | None], key: str) -> str:
        value = row.get(key)
        if value is None:
            raise ValueError("manual_episode_table_value_missing")
        return value

    @staticmethod
    def _optional(row: dict[str, str | None], key: str) -> str | None:
        value = row.get(key)
        return value or None

    @classmethod
    def _optional_date(cls, row: dict[str, str | None], key: str) -> date | None:
        value = cls._optional(row, key)
        return date.fromisoformat(value) if value is not None else None

    @classmethod
    def _optional_int(cls, row: dict[str, str | None], key: str) -> int | None:
        value = cls._optional(row, key)
        return int(value) if value is not None else None


__all__: list[str] = []
