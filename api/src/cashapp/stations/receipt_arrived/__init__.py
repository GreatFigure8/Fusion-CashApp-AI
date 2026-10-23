"""The receipt-arrived consumer role. Submodules load inside ``build``."""

from typing import TYPE_CHECKING

from cashapp.pipeline.roles import Container, RoleSpec

if TYPE_CHECKING:
    from cashapp.stations.receipt_arrived.consumer import ReceiptArrivedConsumer


def build(container: Container) -> "ReceiptArrivedConsumer":
    from cashapp.pipeline.events import TopicNamer
    from cashapp.stations.receipt_arrived.consumer import ReceiptArrivedConsumer

    return ReceiptArrivedConsumer(
        uow_factory=container.uow_factory,
        bus=container.bus,
        group=container.runtime.streaming().consumer_group,
        config=container.config,
        clock=container.clock,
        namer=TopicNamer.from_config(container.runtime.streaming(), container.runtime.env),
    )


ROLE = RoleSpec("receipt-arrived", "consumer", build)

__all__ = ["ROLE", "build"]
