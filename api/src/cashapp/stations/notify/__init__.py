"""The notify consumer role. The consumer module loads inside ``build``."""

from cashapp.pipeline.roles import Container, RoleSpec, Runnable


def build(container: Container) -> Runnable:
    from cashapp.stations.notify.consumer import NotifyConsumer

    return NotifyConsumer.build(container)


ROLE = RoleSpec("notify", "consumer", build)

__all__ = ["ROLE", "build"]
