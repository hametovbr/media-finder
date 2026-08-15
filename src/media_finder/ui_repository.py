"""Persistence-backed UI view models and archive-only catalog mutations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Acquisition,
    AppSetting,
    Collection,
    DownloadClientInstance,
    MediaItem,
    MetadataRevision,
)
from .sdk.types import NormalizedMetadata


class UIRepository:
    """Keep SQLAlchemy entities and query choices out of templates and route handlers."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def active_collections(self) -> list[Collection]:
        with self._sessions() as database:
            return list(
                database.scalars(
                    select(Collection)
                    .where(Collection.archived_at.is_(None))
                    .order_by(Collection.name)
                )
            )

    def archived_collections(self) -> list[Collection]:
        with self._sessions() as database:
            return list(
                database.scalars(
                    select(Collection)
                    .where(Collection.archived_at.is_not(None))
                    .order_by(Collection.name)
                )
            )

    def catalog_items(
        self, *, locale: str, archived: bool, collection_filter: str | None
    ) -> list[dict[str, Any]]:
        with self._sessions() as database:
            query = select(MediaItem).where(
                MediaItem.archived_at.is_not(None) if archived else MediaItem.archived_at.is_(None)
            )
            if collection_filter == "uncategorized":
                query = query.where(MediaItem.collection_id.is_(None))
            elif collection_filter:
                query = query.where(MediaItem.collection_id == collection_filter)
            items: list[dict[str, Any]] = []
            for item in database.scalars(query.order_by(MediaItem.normalized_title)):
                revision = database.get(MetadataRevision, item.current_revision_id)
                effective = revision.effective_payload if revision else None
                titles = effective.get("titles", {}) if effective else {}
                title = titles.get(locale) or next(iter(titles.values()), item.external_id)
                poster_url: str | None = None
                if effective is not None:
                    try:
                        metadata = NormalizedMetadata.model_validate(effective)
                        poster = next(
                            (
                                artwork
                                for artwork in metadata.artwork
                                if artwork.kind.casefold() == "poster"
                            ),
                            None,
                        )
                        poster_url = str(poster.url) if poster is not None else None
                    except Exception:
                        poster_url = None
                latest = database.scalar(
                    select(Acquisition)
                    .where(Acquisition.media_item_id == item.id)
                    .order_by(Acquisition.created_at.desc())
                    .limit(1)
                )
                items.append(
                    {
                        "id": item.id,
                        "title": title,
                        "year": item.year,
                        "kind": item.kind,
                        "provider": item.provider_key,
                        "status": latest.status if latest else None,
                        "poster_url": poster_url,
                    }
                )
            return items

    def acquisitions(self, item_id: str) -> list[Acquisition]:
        with self._sessions() as database:
            return list(
                database.scalars(
                    select(Acquisition)
                    .where(Acquisition.media_item_id == item_id)
                    .order_by(Acquisition.created_at.desc())
                )
            )

    def item_detail(self, item_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        with self._sessions() as database:
            item = database.get(MediaItem, item_id)
            if item is None:
                return None
            revision = database.get(MetadataRevision, item.current_revision_id)
            metadata = revision.effective_payload if revision and revision.effective_payload else {}
            return (
                {
                    "id": item.id,
                    "kind": item.kind,
                    "provider": item.provider_key,
                    "archived": item.archived_at is not None,
                },
                metadata,
            )

    def clients(self, *, archived: bool = False) -> list[DownloadClientInstance]:
        with self._sessions() as database:
            return list(
                database.scalars(
                    select(DownloadClientInstance)
                    .where(
                        DownloadClientInstance.archived_at.is_not(None)
                        if archived
                        else DownloadClientInstance.archived_at.is_(None)
                    )
                    .order_by(DownloadClientInstance.name)
                )
            )

    def change_client(self, client_id: str, *, restore: bool) -> bool:
        with self._sessions() as database:
            instance = database.get(DownloadClientInstance, client_id)
            if instance is None:
                return False
            instance.archived_at = None if restore else datetime.now(UTC)
            database.commit()
            return True

    def has_setting(self, key: str) -> bool:
        with self._sessions() as database:
            return database.get(AppSetting, key) is not None

    def create_collection(self, name: str) -> None:
        with self._sessions() as database:
            database.add(Collection(name=name))
            database.commit()

    def change_collection(self, collection_id: str, *, restore: bool) -> bool:
        with self._sessions() as database:
            collection = database.get(Collection, collection_id)
            if collection is None:
                return False
            collection.archived_at = None if restore else datetime.now(UTC)
            database.commit()
            return True

    def change_item(
        self,
        item_id: str,
        action: Literal["archive", "restore", "move"],
        collection_id: str | None = None,
    ) -> Literal["ok", "item_missing", "collection_unavailable"]:
        with self._sessions() as database:
            item = database.get(MediaItem, item_id)
            if item is None:
                return "item_missing"
            if action == "archive":
                item.archived_at = datetime.now(UTC)
            elif action == "restore":
                item.archived_at = None
            else:
                if collection_id is not None:
                    collection = database.get(Collection, collection_id)
                    if collection is None or collection.archived_at is not None:
                        return "collection_unavailable"
                item.collection_id = collection_id
            database.commit()
            return "ok"

    def store_setting(self, key: str, payload: dict[str, Any]) -> None:
        with self._sessions() as database:
            setting = database.get(AppSetting, key)
            if setting is None:
                setting = AppSetting(key=key, value_payload=payload, secret_reference=False)
                database.add(setting)
            else:
                setting.value_payload = payload
            database.commit()
