"""POLLER_HEARTBEAT: when each of the two pollers last completed a cycle.

The flow monitor reads it for "the intake poller last checked the mailbox N minutes ago". This
module also declares the three indexes the flow monitor's queries need on tables other stories
own, so their model files stay untouched. The Alembic revision creates the same indexes.
"""

from datetime import datetime

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.types import UtcDateTime
from cashapp.domain.clock import utcnow


class PollerHeartbeat(Base):
    __tablename__ = "poller_heartbeat"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_cycle_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )


# The flow stream's one query per tick (changed since), the "received today" KPI, and the
# throughput / dwell scan over STAGE_TRANSITION history.
IX_WORK_ITEM_UPDATED_AT = Index("IX_WORK_ITEM_UPDATED_AT", WorkItem.updated_at)
IX_WORK_ITEM_CREATED_AT = Index("IX_WORK_ITEM_CREATED_AT", WorkItem.created_at)
IX_WIH_ACTION_AT = Index("IX_WIH_ACTION_AT", WorkItemHistory.action, WorkItemHistory.at)
