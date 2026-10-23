"""Turn a Principal into the actor fields of a history row. One definition, reused everywhere."""

from typing import TypedDict

from cashapp.domain.principal import Principal
from cashapp.domain.work_item import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME, ActorKind


class ActorFields(TypedDict):
    actor_kind: ActorKind
    actor_id: str
    actor_name: str


def actor_fields(principal: Principal) -> ActorFields:
    """``HistoryEntry(action=..., **actor_fields(principal), ...)``."""
    if principal.is_system:
        return ActorFields(
            actor_kind=ActorKind.SYSTEM, actor_id=SYSTEM_ACTOR_ID, actor_name=SYSTEM_ACTOR_NAME
        )
    return ActorFields(
        actor_kind=ActorKind.USER, actor_id=principal.subject, actor_name=principal.display_name
    )
