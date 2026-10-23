"""s11: CUSTOMER_RESOLUTION (the customer resolved for each work item).

Revision ID: s11_customer_resolution
Revises: s06_artifact_part
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision: str = "s11_customer_resolution"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision: str | None = "s06_artifact_part"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_resolution",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("anchor_customer_number", sa.String(100), nullable=False),
        sa.Column("related_customer_numbers", JsonDoc(), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("alias_ids", JsonDoc(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("transactions", JsonDoc(), nullable=False),
        sa.Column("flags", JsonDoc(), nullable=False),
        sa.Column("line_findings", JsonDoc(), nullable=False),
        sa.Column("anchor_line_no", sa.Integer(), nullable=True),
        sa.Column("currency_source", sa.String(30), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_CUSTOMER_RESOLUTION"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_CUSTRES_WORK_ITEM"),
    )
    op.create_index(
        "IX_CUSTRES_ITEM_CREATED", "customer_resolution", ["work_item_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("IX_CUSTRES_ITEM_CREATED", table_name="customer_resolution")
    op.drop_table("customer_resolution")
