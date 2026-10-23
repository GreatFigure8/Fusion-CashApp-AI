"""s48: MCP_CALL_LOG (one row per Fusion MCP tool call: hashes and counts, never SQL or bodies).

Revision ID: s48_mcp_call_log
Revises: s45_retention_purge

The `mcp.*` config keys need no seed row: the registry default is in effect until an admin saves
a value.
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import UtcDateTime

revision = "s48_mcp_call_log"
# The head when this was coded; the merger re-points this to the engine-control-api revision
# (split.md merge order) and checks for a single head.
down_revision = "s45_retention_purge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_call_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("tool", sa.String(40), nullable=False),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("target_label", sa.String(200), nullable=True),
        sa.Column("target_hash", sa.String(64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("principal_id", sa.String(200), nullable=True),
        sa.Column("principal_kind", sa.String(10), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_MCP_CALL_LOG"),
    )
    op.create_index("IX_MCP_CALL_LOG_AT", "mcp_call_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("IX_MCP_CALL_LOG_AT", table_name="mcp_call_log")
    op.drop_table("mcp_call_log")
