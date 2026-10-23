"""The Fusion receipt watcher role. Submodules load inside ``build``: discovery imports no SDKs."""

from typing import TYPE_CHECKING

from cashapp.pipeline.roles import Container, RoleSpec

if TYPE_CHECKING:
    from cashapp.pollers.receipt_watcher.watcher import ReceiptWatcher


def build(container: Container) -> "ReceiptWatcher":
    from cashapp.integrations.fusion import FusionClient
    from cashapp.pollers.receipt_watcher.watcher import ReceiptWatcher

    return ReceiptWatcher(
        uow_factory=container.uow_factory,
        fusion=container.resolve(FusionClient),
        config=container.config,
        clock=container.clock,
    )


ROLE = RoleSpec("receipt-watcher", "poller", build)

__all__ = ["ROLE", "build"]
