"""s08: EXTRACTION_READING (one row per reader attempt).

Revision ID: 0004_s08_extraction_reading
Revises: 0003_config
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision: str = "0004_s08_extraction_reading"
# The head when this was coded; the merger re-points this if another story merges first.
down_revision: str | None = "0003_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_reading",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("reader", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("output", JsonDoc(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("effort", sa.String(10), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("purged_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_EXTRACTION_READING"),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["work_item.id"], name="FK_EXTRACTION_READING_WI"
        ),
    )
    op.create_index(
        "IX_EXTRACTION_READING_ITEM",
        "extraction_reading",
        ["work_item_id", "reader", "attempt"],
    )


def downgrade() -> None:
    op.drop_index("IX_EXTRACTION_READING_ITEM", table_name="extraction_reading")
    op.drop_table("extraction_reading")
