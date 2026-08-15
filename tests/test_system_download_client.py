from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from media_finder.db import create_database, migrate_to_head, session_factory
from media_finder.models import AppSetting, DownloadClientInstance
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID, ensure_system_qbittorrent
from media_finder_core.acquisition import AcquisitionRequest
from sqlalchemy import select

from alembic import command


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_fresh_database_has_one_idempotent_system_qbittorrent(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    migrate_to_head(url)
    engine = create_database(url)

    with session_factory(engine)() as database:
        first = ensure_system_qbittorrent(database)
        second = ensure_system_qbittorrent(database)
        rows = list(database.scalars(select(DownloadClientInstance)))

    assert first.id == second.id == SYSTEM_QBITTORRENT_ID
    assert [(row.name, row.module_key, row.config_payload, row.system_owned) for row in rows] == [
        ("qBittorrent", "qbittorrent", {}, True)
    ]
    engine.dispose()


def test_upgrade_rejects_acquisitions_without_truthful_module_snapshots(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    config = _config(url)
    command.upgrade(config, "0002_acquisition_submission")
    engine = create_database(url)
    legacy_id = str(uuid4())
    item_id = str(uuid4())
    revision_id = str(uuid4())
    acquisition_id = uuid4()
    now = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO download_client_instances "
                "(id, name, module_key, config_payload, archived_at, created_at) "
                "VALUES (:id, 'qBittorrent', 'qbittorrent', :config, NULL, :created)"
            ),
            {"id": legacy_id, "config": '{"password_ref":"env:OLD_SECRET"}', "created": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO media_items "
                "(id, provider_key, external_id, kind, normalized_title, year, created_at) "
                "VALUES (:id, 'manual', 'legacy', 'movie', 'Legacy', 2020, :created)"
            ),
            {"id": item_id, "created": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO metadata_revisions "
                "(id, media_item_id, revision_number, provider_key, external_id, locale, "
                "schema_version, provenance_payload, raw_payload, normalized_payload, "
                "overrides_payload, effective_payload, created_at) VALUES "
                "(:id, :item, 1, 'manual', 'legacy', 'en', '1', '{}', '{}', '{}', "
                "'{}', '{}', :created)"
            ),
            {"id": revision_id, "item": item_id, "created": now},
        )
        connection.execute(
            sa.text("UPDATE media_items SET current_revision_id=:revision WHERE id=:item"),
            {"revision": revision_id, "item": item_id},
        )
        connection.execute(
            sa.text(
                "INSERT INTO acquisitions "
                "(id, media_item_id, metadata_revision_id, download_client_instance_id, "
                "idempotency_key, naming_profile, status, destination, created_at, updated_at) "
                "VALUES (:id, :item, :revision, :client, 'legacy-acq', 'jellyfin-v1', "
                "'submitted', 'movies', :created, :created)"
            ),
            {
                "id": acquisition_id.hex,
                "item": item_id,
                "revision": revision_id,
                "client": legacy_id,
                "created": now,
            },
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="cannot reconstruct acquisition module snapshots"):
        command.upgrade(config, "head")


def test_schema_downgrade_requires_the_documented_pre_upgrade_backup(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'downgrade.db'}"
    config = _config(url)
    command.upgrade(config, "head")

    with pytest.raises(RuntimeError, match="pre-upgrade database backup"):
        command.downgrade(config, "0002_acquisition_submission")


def test_upgrade_recovers_partial_ddl_scrubs_settings_and_avoids_name_collisions(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{tmp_path / 'recovery.db'}"
    config = _config(url)
    command.upgrade(config, "0002_acquisition_submission")
    engine = create_database(url)
    legacy_id = "11111111-1111-4111-8111-111111111111"
    collision_id = "22222222-2222-4222-8222-222222222222"
    now = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO download_client_instances "
                "(id, name, module_key, config_payload, archived_at, created_at) VALUES "
                "(:legacy, 'qBittorrent', 'qbittorrent', '{}', NULL, :created), "
                "(:collision, 'qBittorrent (legacy 11111111)', 'qbittorrent', '{}', NULL, "
                ":created)"
            ),
            {"legacy": legacy_id, "collision": collision_id, "created": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO app_settings "
                "(key, value_payload, secret_reference, updated_at) VALUES "
                "('metadata_provider:tmdb', :provider, 1, :updated), "
                "('prowlarr', :prowlarr, 1, :updated), "
                "('maintenance:last_run', :maintenance, 0, :updated)"
            ),
            {
                "provider": '{"api_token":"env:OLD_TMDB_TOKEN"}',
                "prowlarr": '{"base_url":"https://old.invalid","api_key_ref":"env:OLD"}',
                "maintenance": '{"at":"2026-01-01T00:00:00Z"}',
                "updated": now,
            },
        )
        # Reproduce SQLite's non-transactional DDL state after an interrupted migration.
        connection.execute(
            sa.text(
                "ALTER TABLE download_client_instances ADD COLUMN system_owned BOOLEAN "
                "DEFAULT 0 NOT NULL"
            )
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database(url)
    with session_factory(engine)() as database:
        clients = list(database.scalars(select(DownloadClientInstance)))
        setting_keys = set(database.scalars(select(AppSetting.key)))

    names = [client.name for client in clients]
    migrated_legacy = next(client for client in clients if client.id == legacy_id)
    assert len(names) == len(set(names))
    assert "qBittorrent" in names
    assert migrated_legacy.name == "qBittorrent (legacy 11111111) 2"
    assert setting_keys == {"maintenance:last_run"}
    engine.dispose()


def test_acquisition_request_has_no_mutable_client_instance_selection() -> None:
    assert "client_instance_id" not in {field.name for field in fields(AcquisitionRequest)}
