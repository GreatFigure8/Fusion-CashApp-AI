"""s19: POLLER_HEARTBEAT and the indexes behind the flow monitor's queries.

Revision ID: s19_flow_monitor
Revises: s45_retention_purge
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import UtcDateTime

revision = "s19_flow_monitor"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s15_line_result_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "poller_heartbeat",
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("last_cycle_at", UtcDateTime(), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name", name="PK_POLLER_HEARTBEAT"),
    )
    op.create_index("IX_WORK_ITEM_UPDATED_AT", "work_item", ["updated_at"])
    op.create_index("IX_WORK_ITEM_CREATED_AT", "work_item", ["created_at"])
    op.create_index("IX_WIH_ACTION_AT", "work_item_history", ["action", "at"])


def downgrade() -> None:
    op.drop_index("IX_WIH_ACTION_AT", table_name="work_item_history")
    op.drop_index("IX_WORK_ITEM_CREATED_AT", table_name="work_item")
    op.drop_index("IX_WORK_ITEM_UPDATED_AT", table_name="work_item")
    op.drop_table("poller_heartbeat")
