"""The pipeline runtime: events, bus, outbox relay, stage runner, retry forwarder and roles."""

from cashapp.pipeline.relay import RELAY_ROLE
from cashapp.pipeline.retry import RETRY_ROLE
from cashapp.pipeline.roles import RoleSpec

ROLES: list[RoleSpec] = [RELAY_ROLE, RETRY_ROLE]

__all__ = ["RELAY_ROLE", "RETRY_ROLE", "ROLES"]
