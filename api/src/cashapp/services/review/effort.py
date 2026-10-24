"""The one effort lookup for the readers and the adjudicator."""

from cashapp.data.models.work_item import WorkItem
from cashapp.domain import config_keys as ck
from cashapp.domain.work_item import SourceKind
from cashapp.services.config import ConfigSnapshot
from cashapp.services.config_groups import ModelRole


def effort_for(item: WorkItem, role: ModelRole, config: ConfigSnapshot) -> str | None:
    """Auto-fix override, then ``review.effort`` for uploaded (MANUAL) items, then the role."""
    hints = item.fix_hints or {}
    override = hints.get("effort")
    if override:
        return override
    if item.source_kind is SourceKind.MANUAL:
        return config.get(ck.REVIEW_EFFORT)
    return role.effort
