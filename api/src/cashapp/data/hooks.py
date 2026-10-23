"""The one place the pipeline hooks into the ORM session lifecycle.

Kept inside the data layer so no other package imports SQLAlchemy.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import event

from cashapp.data.uow import UnitOfWork


def after_commit(uow: UnitOfWork, callback: Callable[[], None]) -> None:
    """Run ``callback`` once, after the next real commit of ``uow``'s session.

    A rollback fires nothing. The callback is synchronous and must not raise or block
    (it is used to wake the outbox relay).
    """

    def _fire(_session: Any) -> None:
        callback()

    event.listen(uow.session.sync_session, "after_commit", _fire, once=True)
