"""ui01: assistant chat threads, messages, pending tool calls and the tool-run audit.

Revision ID: ui01_chat_agent_tool_registry
Revises: s45_retention_purge
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "ui01_chat_agent_tool_registry"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s45_retention_purge"
branch_labels = None
depends_on = None


def _big() -> sa.types.TypeEngine[int]:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _id() -> sa.Column[int]:
    return sa.Column("id", _big(), sa.Identity(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "chat_thread",
        _id(),
        sa.Column("owner_subject", sa.String(200), nullable=False),
        sa.Column("owner_name", sa.String(200), nullable=False),
        sa.Column("prompt_key", sa.String(20), nullable=False),
        sa.Column("context_kind", sa.String(20), nullable=False),
        sa.Column("context_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_CHAT_THREAD"),
    )
    op.create_index("IX_CHAT_THREAD_OWNER_UPDATED", "chat_thread", ["owner_subject", "updated_at"])

    op.create_table(
        "chat_message",
        _id(),
        sa.Column("thread_id", _big(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", JsonDoc(), nullable=False),
        sa.Column("display_text", sa.String(4000), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_CHAT_MESSAGE"),
        sa.ForeignKeyConstraint(["thread_id"], ["chat_thread.id"], name="FK_CHAT_MESSAGE_THREAD"),
        sa.UniqueConstraint("thread_id", "seq", name="UQ_CHAT_MESSAGE_THREAD_SEQ"),
    )

    op.create_table(
        "chat_pending_tool_call",
        _id(),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("thread_id", _big(), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("input", JsonDoc(), nullable=False),
        sa.Column("principal_subject", sa.String(200), nullable=False),
        sa.Column("principal_name", sa.String(200), nullable=False),
        sa.Column("preview", JsonDoc(), nullable=False),
        sa.Column("expires_at", UtcDateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decided_at", UtcDateTime(), nullable=True),
        sa.Column("decided_by", sa.String(200), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_CHAT_PENDING_TOOL_CALL"),
        sa.ForeignKeyConstraint(["thread_id"], ["chat_thread.id"], name="FK_CHAT_PENDING_THREAD"),
        sa.UniqueConstraint("call_id", name="UQ_CHAT_PENDING_CALL_ID"),
    )
    op.create_index(
        "IX_CHAT_PENDING_THREAD_STATUS", "chat_pending_tool_call", ["thread_id", "status"]
    )

    op.create_table(
        "chat_tool_run",
        _id(),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("audit_label", sa.String(120), nullable=False),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("input_summary", sa.String(400), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("summary", sa.String(400), nullable=True),
        sa.Column("result_card", JsonDoc(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_CHAT_TOOL_RUN"),
    )
    op.create_index("IX_CHAT_TOOL_RUN_AT", "chat_tool_run", ["at"])
    op.create_index("IX_CHAT_TOOL_RUN_ACTOR_AT", "chat_tool_run", ["actor_subject", "at"])
    op.create_index("IX_CHAT_TOOL_RUN_THREAD", "chat_tool_run", ["thread_id"])


def downgrade() -> None:
    op.drop_index("IX_CHAT_TOOL_RUN_THREAD", table_name="chat_tool_run")
    op.drop_index("IX_CHAT_TOOL_RUN_ACTOR_AT", table_name="chat_tool_run")
    op.drop_index("IX_CHAT_TOOL_RUN_AT", table_name="chat_tool_run")
    op.drop_table("chat_tool_run")
    op.drop_index("IX_CHAT_PENDING_THREAD_STATUS", table_name="chat_pending_tool_call")
    op.drop_table("chat_pending_tool_call")
    op.drop_table("chat_message")
    op.drop_index("IX_CHAT_THREAD_OWNER_UPDATED", table_name="chat_thread")
    op.drop_table("chat_thread")
