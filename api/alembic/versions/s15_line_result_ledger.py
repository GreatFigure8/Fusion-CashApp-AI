"""s15: LINE_RESULT (per-line outcome) and APPLICATION_LEDGER (every planned/applied application).

Revision ID: s15_line_result_ledger
Revises: s45_retention_purge
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, MoneyNumeric, UtcDateTime

revision: str = "s15_line_result_ledger"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision: str | None = "s13_receipt_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ID = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "line_result",
        sa.Column("id", _ID, sa.Identity(), nullable=False),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("transaction_number", sa.String(100), nullable=True),
        sa.Column("customer_trx_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("stated_amount", MoneyNumeric, nullable=True),
        sa.Column("balance_before", MoneyNumeric, nullable=True),
        sa.Column("applied_amount", MoneyNumeric, nullable=True),
        sa.Column("discount_amount", MoneyNumeric, nullable=True),
        sa.Column("residual", MoneyNumeric, nullable=True),
        sa.Column("line_status", sa.String(60), nullable=True),
        sa.Column("target_status", sa.String(60), nullable=True),
        sa.Column("merged_into", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_LINE_RESULT"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_LINE_RESULT_WI"),
        sa.UniqueConstraint("work_item_id", "line_no", name="UQ_LINE_RESULT_ITEM_LINE"),
    )
    op.create_table(
        "application_ledger",
        sa.Column("id", _ID, sa.Identity(), nullable=False),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("receipt_number", sa.String(100), nullable=True),
        sa.Column("customer_trx_id", sa.BigInteger(), nullable=False),
        sa.Column("apply_seq", sa.Integer(), nullable=False),
        sa.Column("amount", MoneyNumeric, nullable=False),
        sa.Column("discount_amount", MoneyNumeric, nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("fusion_application_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("request", JsonDoc(), nullable=True),
        sa.Column("response_messages", JsonDoc(), nullable=True),
        sa.Column("applied_at", UtcDateTime(), nullable=True),
        sa.Column("applied_by", sa.String(255), nullable=True),
        sa.Column("reversed_at", UtcDateTime(), nullable=True),
        sa.Column("reversed_by", sa.String(255), nullable=True),
        sa.Column("reversal_reason", sa.String(1000), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_APPLICATION_LEDGER"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_APP_LEDGER_WI"),
        sa.UniqueConstraint("idempotency_key", name="UQ_APP_LEDGER_IDEM_KEY"),
    )
    op.create_index("IX_APP_LEDGER_ITEM_STATUS", "application_ledger", ["work_item_id", "status"])
    op.create_index("IX_APP_LEDGER_RECEIPT", "application_ledger", ["receipt_id"])


def downgrade() -> None:
    op.drop_index("IX_APP_LEDGER_RECEIPT", table_name="application_ledger")
    op.drop_index("IX_APP_LEDGER_ITEM_STATUS", table_name="application_ledger")
    op.drop_table("application_ledger")
    op.drop_table("line_result")
