"""Persist immutable acquisition module and correlation snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_acquisition_module_snapshots"
down_revision: str | Sequence[str] | None = "0003_environment_owned_qbittorrent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM acquisitions")):
        raise RuntimeError(
            "cannot reconstruct acquisition module snapshots; recreate the disposable "
            "pre-release database"
        )
    op.add_column(
        "acquisitions",
        sa.Column("correlation", sa.String(200), nullable=False),
    )
    op.add_column(
        "acquisitions",
        sa.Column("release_provider_id", sa.String(100), nullable=False),
    )
    op.add_column(
        "acquisitions",
        sa.Column("release_provider_version", sa.String(100), nullable=False),
    )
    op.add_column(
        "acquisitions",
        sa.Column("download_client_module_id", sa.String(100), nullable=False),
    )
    op.add_column(
        "acquisitions",
        sa.Column("download_client_module_version", sa.String(100), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("acquisitions", "download_client_module_version")
    op.drop_column("acquisitions", "download_client_module_id")
    op.drop_column("acquisitions", "release_provider_version")
    op.drop_column("acquisitions", "release_provider_id")
    op.drop_column("acquisitions", "correlation")
