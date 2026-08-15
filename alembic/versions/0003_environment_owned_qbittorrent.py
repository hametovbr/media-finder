"""Create the environment-owned qBittorrent identity and scrub legacy clients."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_environment_owned_qbittorrent"
down_revision: str | Sequence[str] | None = "0002_acquisition_submission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_QBITTORRENT_ID = "00000000-0000-5000-8000-000000000001"


def upgrade() -> None:
    connection = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(connection).get_columns("download_client_instances")
    }
    if "system_owned" not in columns:
        op.add_column(
            "download_client_instances",
            sa.Column("system_owned", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    connection.execute(
        sa.text("DELETE FROM app_settings WHERE key = 'prowlarr' OR key LIKE 'metadata_provider:%'")
    )
    conflicting_name = connection.execute(
        sa.text(
            "SELECT id FROM download_client_instances "
            "WHERE name = 'qBittorrent' AND id != :system_id"
        ),
        {"system_id": SYSTEM_QBITTORRENT_ID},
    ).scalar_one_or_none()
    if conflicting_name is not None:
        used_names = set(
            connection.execute(sa.text("SELECT name FROM download_client_instances")).scalars()
        )
        base_name = f"qBittorrent (legacy {str(conflicting_name)[:8]})"
        legacy_name = base_name
        suffix = 2
        while legacy_name in used_names:
            legacy_name = f"{base_name} {suffix}"
            suffix += 1
        connection.execute(
            sa.text("UPDATE download_client_instances SET name = :name WHERE id = :legacy_id"),
            {
                "name": legacy_name,
                "legacy_id": conflicting_name,
            },
        )
    connection.execute(
        sa.text(
            "UPDATE download_client_instances SET config_payload = '{}', "
            "archived_at = COALESCE(archived_at, CURRENT_TIMESTAMP), system_owned = 0 "
            "WHERE id != :system_id"
        ),
        {"system_id": SYSTEM_QBITTORRENT_ID},
    )
    existing_system = connection.execute(
        sa.text("SELECT 1 FROM download_client_instances WHERE id = :system_id"),
        {"system_id": SYSTEM_QBITTORRENT_ID},
    ).scalar_one_or_none()
    if existing_system is None:
        connection.execute(
            sa.text(
                "INSERT INTO download_client_instances "
                "(id, name, module_key, config_payload, system_owned, archived_at, created_at) "
                "VALUES (:system_id, 'qBittorrent', 'qbittorrent', '{}', 1, NULL, "
                "CURRENT_TIMESTAMP)"
            ),
            {"system_id": SYSTEM_QBITTORRENT_ID},
        )
    else:
        connection.execute(
            sa.text(
                "UPDATE download_client_instances SET name = 'qBittorrent', "
                "module_key = 'qbittorrent', config_payload = '{}', system_owned = 1, "
                "archived_at = NULL WHERE id = :system_id"
            ),
            {"system_id": SYSTEM_QBITTORRENT_ID},
        )


def downgrade() -> None:
    raise RuntimeError(
        "environment-only integration rollback requires the pre-upgrade database backup"
    )
