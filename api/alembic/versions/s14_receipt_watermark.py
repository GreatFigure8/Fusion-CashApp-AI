"""s14: RECEIPT_WATERMARK (the Fusion receipt watcher's high-water mark, one row per pod).

Revision ID: s14_receipt_watermark
Revises: s06_artifact_part
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision: str = "s14_receipt_watermark"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision: str | None = "s06_artifact_part"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "receipt_watermark",
        sa.Column("pod", sa.String(100), nullable=False),
        sa.Column("high_water_mark", UtcDateTime(), nullable=False),
        sa.Column("seen_at_mark", JsonDoc(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("pod", name="PK_RECEIPT_WATERMARK"),
    )


def downgrade() -> None:
    op.drop_table("receipt_watermark")
