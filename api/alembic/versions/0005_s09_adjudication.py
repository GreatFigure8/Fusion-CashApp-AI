"""s09: ADJUDICATION (the adjudicated extraction and where each value came from).

Revision ID: 0005_s09_adjudication
Revises: s06_artifact_part
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision: str = "0005_s09_adjudication"
# The head when this was coded; the merger re-points this if another story merges first.
down_revision: str | None = "s06_artifact_part"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adjudication",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("reading_a_id", sa.BigInteger(), nullable=True),
        sa.Column("reading_b_id", sa.BigInteger(), nullable=True),
        sa.Column("missing_reader", sa.String(40), nullable=True),
        sa.Column("final", JsonDoc(), nullable=True),
        sa.Column("provenance", JsonDoc(), nullable=False),
        sa.Column("disagreements", JsonDoc(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("edited_by", sa.String(255), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("purged_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_ADJUDICATION"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_ADJUDICATION_WI"),
        sa.ForeignKeyConstraint(
            ["reading_a_id"], ["extraction_reading.id"], name="FK_ADJUDICATION_RA"
        ),
        sa.ForeignKeyConstraint(
            ["reading_b_id"], ["extraction_reading.id"], name="FK_ADJUDICATION_RB"
        ),
    )
    op.create_index("IX_ADJUDICATION_ITEM", "adjudication", ["work_item_id", "created_at"])


def downgrade() -> None:
    op.drop_index("IX_ADJUDICATION_ITEM", table_name="adjudication")
    op.drop_table("adjudication")
