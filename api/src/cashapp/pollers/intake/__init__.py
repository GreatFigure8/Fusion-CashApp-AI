"""The intake poller role."""

from cashapp.integrations.storage.base import ObjectStore
from cashapp.pipeline.roles import Container, RoleSpec
from cashapp.pollers.intake.poller import ROLE_NAME, IntakePoller
from cashapp.pollers.intake.sources import build_sources


def build(container: Container) -> IntakePoller:
    return IntakePoller(
        container=container,
        sources=build_sources(container.runtime),
        object_store=container.resolve(ObjectStore),
    )


ROLE = RoleSpec(ROLE_NAME, "poller", build)

__all__ = ["ROLE", "build"]
