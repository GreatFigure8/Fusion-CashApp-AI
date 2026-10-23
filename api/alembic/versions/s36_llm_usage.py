"""s36: LLM_USAGE (one row per model call) and LLM_BUDGET_ALERT (once-per-day budget marker).

Revision ID: s36_llm_usage
Revises: s06_artifact_part
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import UtcDateTime

revision = "s36_llm_usage"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s14_receipt_watermark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("work_item_id", sa.BigInteger(), nullable=True),
        sa.Column("station", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("schema_version", sa.String(20), nullable=True),
        sa.Column("effort", sa.String(10), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6, asdecimal=True), nullable=True),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("usage_day", sa.Date(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_LLM_USAGE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_item.id"], name="FK_LLM_USAGE_WI"),
    )
    op.create_index("IX_LLM_USAGE_DAY", "llm_usage", ["usage_day", "station"])
    op.create_index("IX_LLM_USAGE_ITEM", "llm_usage", ["work_item_id", "created_at"])
    op.create_index("IX_LLM_USAGE_ROLE_AT", "llm_usage", ["role", "created_at"])

    op.create_table(
        "llm_budget_alert",
        sa.Column("alert_day", sa.Date(), nullable=False),
        sa.Column("limit_usd", sa.Numeric(18, 2, asdecimal=True), nullable=False),
        sa.Column("total_usd", sa.Numeric(12, 6, asdecimal=True), nullable=False),
        sa.Column("emitted_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("alert_day", name="PK_LLM_BUDGET_ALERT"),
    )


def downgrade() -> None:
    op.drop_table("llm_budget_alert")
    op.drop_index("IX_LLM_USAGE_ROLE_AT", table_name="llm_usage")
    op.drop_index("IX_LLM_USAGE_ITEM", table_name="llm_usage")
    op.drop_index("IX_LLM_USAGE_DAY", table_name="llm_usage")
    op.drop_table("llm_usage")
