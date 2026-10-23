"""s42: NOTIFICATION_LOG (one row per notification sent, failed or suppressed).

Revision ID: s42_notification_log
Revises: s36_llm_usage
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s42_notification_log"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s36_llm_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("recipients", JsonDoc(), nullable=False),
        sa.Column("subject", sa.String(400), nullable=False),
        sa.Column("event_ids", JsonDoc(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("sent_at", UtcDateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(2000), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_NOTIFICATION_LOG"),
    )
    op.create_index("IX_NOTIFICATION_LOG_KIND_AT", "notification_log", ["kind", "sent_at"])
    op.create_index("IX_NOTIFICATION_LOG_AT", "notification_log", ["sent_at"])


def downgrade() -> None:
    op.drop_index("IX_NOTIFICATION_LOG_AT", table_name="notification_log")
    op.drop_index("IX_NOTIFICATION_LOG_KIND_AT", table_name="notification_log")
    op.drop_table("notification_log")
