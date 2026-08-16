"""Create the clean pre-release core schema."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_clean_core"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "maintenance_execution_state",
        sa.Column("task_key", sa.String(100), primary_key=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "media_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_key", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "collection_id",
            sa.String(36),
            sa.ForeignKey("collections.id", ondelete="RESTRICT"),
        ),
        sa.Column("normalized_title", sa.String(500)),
        sa.Column("year", sa.Integer),
        sa.Column("current_revision_id", sa.String(36)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_key", "external_id", name="uq_media_identity"),
    )
    op.create_index("ix_media_similarity", "media_items", ["normalized_title", "year"])
    op.create_table(
        "metadata_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.String(36),
            sa.ForeignKey("media_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("provider_key", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("locale", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("provenance_payload", sa.JSON, nullable=False),
        sa.Column("raw_payload", sa.JSON),
        sa.Column("normalized_payload", sa.JSON),
        sa.Column("overrides_payload", sa.JSON, nullable=False),
        sa.Column("effective_payload", sa.JSON),
        sa.Column("refresh_after", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("maintenance_status", sa.String(30)),
        sa.Column("maintenance_error_code", sa.String(200)),
        sa.Column("maintenance_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("media_item_id", "revision_number", name="uq_item_revision"),
    )
    op.create_table(
        "acquisitions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.String(36),
            sa.ForeignKey("media_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "metadata_revision_id",
            sa.String(36),
            sa.ForeignKey("metadata_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("naming_profile", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("destination", sa.String(500), nullable=False),
        sa.Column("correlation", sa.String(200), nullable=False),
        sa.Column("release_title", sa.String(1000)),
        sa.Column("indexer", sa.String(300)),
        sa.Column("guid", sa.String(512)),
        sa.Column("infohash", sa.String(100)),
        sa.Column("source_page_url", sa.Text),
        sa.Column("release_provider_id", sa.String(100), nullable=False),
        sa.Column("release_provider_version", sa.String(100), nullable=False),
        sa.Column("download_client_module_id", sa.String(100), nullable=False),
        sa.Column("download_client_module_version", sa.String(100), nullable=False),
        sa.Column("external_task_id", sa.String(500)),
        sa.Column("failure_code", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_acquisition_idempotency"),
    )


def downgrade() -> None:
    op.drop_table("acquisitions")
    op.drop_table("metadata_revisions")
    op.drop_index("ix_media_similarity", table_name="media_items")
    op.drop_table("media_items")
    op.drop_table("maintenance_execution_state")
    op.drop_table("collections")
