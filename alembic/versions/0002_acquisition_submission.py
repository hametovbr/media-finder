"""Persist acquisition destination and accepted client task identity."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_acquisition_submission"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "acquisitions",
        sa.Column("destination", sa.String(500), nullable=False, server_default=""),
    )
    op.add_column("acquisitions", sa.Column("external_task_id", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("acquisitions", "external_task_id")
    op.drop_column("acquisitions", "destination")
