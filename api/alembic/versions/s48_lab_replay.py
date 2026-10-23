"""s48: matching lab (LAB_CANDIDATE, LAB_REPLAY, LAB_REPLAY_ITEM) and CONFIG_CHANGE lab columns.

Revision ID: s48_lab_replay
Revises: s48_report_export
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s48_lab_replay"
# The head when this was coded; the merger re-points this and checks for a single head.
down_revision = "s48_report_export"
branch_labels = None
depends_on = None


def _id() -> sa.Column[int]:
    return sa.Column(
        "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.Identity(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "lab_candidate",
        _id(),
        sa.Column("changes", JsonDoc(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("base_key_versions", JsonDoc(), nullable=False),
        sa.Column("base_values", JsonDoc(), nullable=False),
        sa.Column("rationale", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("created_by_name", sa.String(256), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("closed_by", sa.String(256), nullable=True),
        sa.Column("closed_at", UtcDateTime(), nullable=True),
        sa.Column("close_reason", sa.String(1000), nullable=True),
        sa.Column("promoted_version", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_LAB_CANDIDATE"),
    )
    op.create_index("IX_LAB_CAND_STATUS_AT", "lab_candidate", ["status", "created_at"])

    op.create_table(
        "lab_replay",
        _id(),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("live_version", sa.Integer(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("newly_matched", sa.Integer(), nullable=False),
        sa.Column("newly_failed", sa.Integer(), nullable=False),
        sa.Column("newly_ambiguous", sa.Integer(), nullable=False),
        sa.Column("money_by_currency", JsonDoc(), nullable=False),
        sa.Column("started_by", sa.String(256), nullable=False),
        sa.Column("started_at", UtcDateTime(), nullable=False),
        sa.Column("heartbeat_at", UtcDateTime(), nullable=False),
        sa.Column("finished_at", UtcDateTime(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("runner_boot_id", sa.String(36), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_LAB_REPLAY"),
        sa.ForeignKeyConstraint(["candidate_id"], ["lab_candidate.id"], name="FK_LAB_REPLAY_CAND"),
    )
    op.create_index("IX_LAB_REPLAY_CAND", "lab_replay", ["candidate_id", "started_at"])
    op.create_index("IX_LAB_REPLAY_STATUS_FIN", "lab_replay", ["status", "finished_at"])

    op.create_table(
        "lab_replay_item",
        _id(),
        sa.Column("replay_id", sa.BigInteger(), nullable=False),
        sa.Column("work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2, asdecimal=True), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("before_outcome", sa.String(20), nullable=False),
        sa.Column("after_outcome", sa.String(20), nullable=False),
        sa.Column("before_receipt_id", sa.BigInteger(), nullable=True),
        sa.Column("after_receipt_id", sa.BigInteger(), nullable=True),
        sa.Column("changed", sa.Boolean(create_constraint=False), nullable=False),
        sa.Column("since_applied", sa.Boolean(create_constraint=False), nullable=False),
        sa.Column("detail", JsonDoc(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="PK_LAB_REPLAY_ITEM"),
        sa.ForeignKeyConstraint(["replay_id"], ["lab_replay.id"], name="FK_LAB_RI_REPLAY"),
    )
    op.create_index("IX_LAB_RI_REPLAY_CHANGED", "lab_replay_item", ["replay_id", "changed"])
    op.create_index("IX_LAB_RI_WORK_ITEM", "lab_replay_item", ["work_item_id"])

    op.add_column("config_change", sa.Column("change_set_id", sa.Integer(), nullable=True))
    op.add_column("config_change", sa.Column("lab_candidate_id", sa.Integer(), nullable=True))
    op.add_column("config_change", sa.Column("lab_replay_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("config_change", "lab_replay_id")
    op.drop_column("config_change", "lab_candidate_id")
    op.drop_column("config_change", "change_set_id")
    op.drop_index("IX_LAB_RI_WORK_ITEM", table_name="lab_replay_item")
    op.drop_index("IX_LAB_RI_REPLAY_CHANGED", table_name="lab_replay_item")
    op.drop_table("lab_replay_item")
    op.drop_index("IX_LAB_REPLAY_STATUS_FIN", table_name="lab_replay")
    op.drop_index("IX_LAB_REPLAY_CAND", table_name="lab_replay")
    op.drop_table("lab_replay")
    op.drop_index("IX_LAB_CAND_STATUS_AT", table_name="lab_candidate")
    op.drop_table("lab_candidate")
