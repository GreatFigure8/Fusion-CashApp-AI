"""s48: BUS_MESSAGE, the database event queue that replaces the Kafka-compatible stream.

Revision ID: s48_bus_message
Revises: s48_app_secret
"""

import sqlalchemy as sa
from alembic import op

from cashapp.data.types import JsonDoc, UtcDateTime

revision = "s48_bus_message"
down_revision = "s48_app_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bus_message",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("msg_key", sa.String(255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("headers", JsonDoc(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("leased_until", UtcDateTime(), nullable=True),
        sa.Column("consumed_at", UtcDateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="PK_BUS_MESSAGE"),
    )
    op.create_index(
        "IX_BUS_MESSAGE_READY", "bus_message", ["topic", "consumed_at", "priority", "id"]
    )


def downgrade() -> None:
    op.drop_index("IX_BUS_MESSAGE_READY", table_name="bus_message")
    op.drop_table("bus_message")
