"""s13: RECEIPT_RESERVATION and MATCH_CANDIDATE (receipt matching).

Revision ID: s13_receipt_matching
Revises: s45_retention_purge
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision: str = "s13_receipt_matching"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision: str | None = "s45_retention_purge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_column() -> sa.Column[int]:
    return sa.Column(
        "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.Identity(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "receipt_reservation",
        _id_column(),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("receipt_number", sa.String(100), nullable=True),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("reserved_at", UtcDateTime(), nullable=False),
        sa.Column("released_at", UtcDateTime(), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_RECEIPT_RESERVATION"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_RR_WORK_ITEM"),
    )
    op.create_index(
        "UX_RR_ACTIVE_RECEIPT",
        "receipt_reservation",
        [sa.text("CASE WHEN STATUS = 'ACTIVE' THEN RECEIPT_ID END")],
        unique=True,
    )
    op.create_index("IX_RR_ITEM_STATUS", "receipt_reservation", ["work_item_id", "status"])

    op.create_table(
        "match_candidate",
        _id_column(),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("receipt_number", sa.String(100), nullable=True),
        sa.Column("qualifies", sa.Boolean(create_constraint=False), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("signals", JsonDoc(), nullable=False),
        sa.Column("chosen", sa.Boolean(create_constraint=False), nullable=False),
        sa.Column("decided_by", sa.String(40), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("reasons", JsonDoc(), nullable=True),
        sa.Column("customer_account_number", sa.String(100), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("unapplied_amount", sa.Numeric(18, 2, asdecimal=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_MATCH_CANDIDATE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_MC_WORK_ITEM"),
    )
    op.create_index("IX_MC_ITEM_ATTEMPT", "match_candidate", ["work_item_id", "attempt"])


def downgrade() -> None:
    op.drop_index("IX_MC_ITEM_ATTEMPT", table_name="match_candidate")
    op.drop_table("match_candidate")
    op.drop_index("IX_RR_ITEM_STATUS", table_name="receipt_reservation")
    op.drop_index("UX_RR_ACTIVE_RECEIPT", table_name="receipt_reservation")
    op.drop_table("receipt_reservation")
