"""Item locking for human work: while a person holds a live lock, automation must not touch it.

Expiry is lazy: ``lock_expires_at <= now`` means free, everywhere. There is no sweeper.
The service flushes and never commits; the caller (router or requeue) owns the transaction.
"""

import importlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.locks import ItemLockRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.domain.stages import ItemState
from cashapp.domain.work_item import HistoryAction
from cashapp.services.actor import actor_fields
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.history import HistoryEntry, record_history

LOCK_HISTORY_EVENTS: Final = ("acquire", "renew_after_expiry", "release", "force_take")


@dataclass(frozen=True, slots=True)
class LockInfo:
    item_id: int
    owner: str
    owner_name: str
    acquired_at: datetime
    expires_at: datetime


class LockError(Exception):
    def __init__(self, item_id: int, message: str | None = None) -> None:
        self.item_id = item_id
        super().__init__(message or f"{type(self).__name__} for item {item_id}")


class ItemNotFound(LockError):  # noqa: N818
    pass


class LockConflict(LockError):  # noqa: N818
    def __init__(self, item_id: int, owner_name: str, acquired_at: datetime) -> None:
        self.owner_name = owner_name
        self.acquired_at = acquired_at
        super().__init__(item_id, f"Item {item_id} is locked by {owner_name}")


class ItemBusy(LockError):  # noqa: N818
    pass


class LockNotHeld(LockError):  # noqa: N818
    pass


class LockForbidden(LockError):  # noqa: N818
    """Missing items:work, or a system principal (automation never takes a human lock)."""


class LockReasonRequired(LockError):  # noqa: N818
    """force_take with a blank reason."""


# --------------------------------------------------------------------------- liveness rules


def is_lock_live(item: WorkItem, now: datetime) -> bool:
    return (
        item.lock_owner is not None
        and item.lock_expires_at is not None
        and item.lock_expires_at > now
    )


def is_locked_for_automation(item: WorkItem, now: datetime) -> bool:
    """The name automation code uses; the same rule as ``WorkItemRepository.claim`` in SQL."""
    return is_lock_live(item, now)


def _is_claim_live(item: WorkItem, now: datetime) -> bool:
    return (
        item.state == ItemState.IN_PROGRESS
        and item.claim_expires_at is not None
        and item.claim_expires_at > now
    )


def _info_of(item: WorkItem) -> LockInfo:
    if item.lock_owner is None or item.lock_acquired_at is None or item.lock_expires_at is None:
        raise LockNotHeld(item.id)
    return LockInfo(
        item_id=item.id,
        owner=item.lock_owner,
        owner_name=item.lock_owner_name or item.lock_owner,
        acquired_at=item.lock_acquired_at,
        expires_at=item.lock_expires_at,
    )


def lock_info_for(item: WorkItem, now: datetime | None = None) -> LockInfo | None:
    """The item's live lock, or None. Expired locks are not reported."""
    moment = now if now is not None else SystemClock().now()
    if not is_lock_live(item, moment):
        return None
    return _info_of(item)


# --------------------------------------------------------------------------- service


class LockService:
    def __init__(self, config: RuntimeConfig | ConfigSnapshot, clock: Clock | None = None) -> None:
        self._config = config
        self._clock: Clock = clock or SystemClock()

    is_locked_for_automation = staticmethod(is_locked_for_automation)
    lock_info_for = staticmethod(lock_info_for)

    @staticmethod
    def assert_held_by(item: WorkItem, principal: Principal, now: datetime) -> None:
        """Raise LockNotHeld unless a live lock owned by ``principal`` is on the item."""
        if not is_lock_live(item, now) or item.lock_owner != principal.subject:
            raise LockNotHeld(item.id)

    async def _lease(self) -> timedelta:
        config = self._config
        locks = await config.locks() if isinstance(config, RuntimeConfig) else config.locks()
        return timedelta(minutes=locks.lease_minutes)

    @staticmethod
    def _require_worker(item_id: int, principal: Principal) -> None:
        if principal.is_system or not principal.can(Permission.ITEMS_WORK):
            raise LockForbidden(item_id, f"Locking requires {Permission.ITEMS_WORK.value}")

    @staticmethod
    async def _load(uow: UnitOfWork, item_id: int) -> WorkItem:
        item = await uow.repo(ItemLockRepository).get_for_lock(item_id)
        if item is None:
            raise ItemNotFound(item_id)
        return item

    async def _history(
        self,
        uow: UnitOfWork,
        item_id: int,
        principal: Principal,
        event: str,
        expires_at: datetime | None,
        *,
        reasoning: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "event": event,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            **(extra or {}),
        }
        entry = HistoryEntry(
            action=HistoryAction.LOCK,
            **actor_fields(principal),
            reasoning=reasoning,
            payload=payload,
        )
        await record_history(uow, item_id, entry, clock=self._clock)

    async def _take(
        self, uow: UnitOfWork, item: WorkItem, principal: Principal, now: datetime
    ) -> LockInfo:
        await uow.repo(ItemLockRepository).write_lock(
            item,
            owner=principal.subject,
            owner_name=principal.display_name,
            acquired_at=now,
            expires_at=now + await self._lease(),
            now=now,
        )
        return _info_of(item)

    async def _extend(
        self, uow: UnitOfWork, item: WorkItem, principal: Principal, now: datetime
    ) -> LockInfo:
        """Push a live own lock's expiry out; ``acquired_at`` is kept."""
        if item.lock_acquired_at is None:
            raise LockNotHeld(item.id)
        await uow.repo(ItemLockRepository).write_lock(
            item,
            owner=principal.subject,
            owner_name=principal.display_name,
            acquired_at=item.lock_acquired_at,
            expires_at=now + await self._lease(),
            now=now,
        )
        return _info_of(item)

    async def acquire(self, uow: UnitOfWork, item_id: int, principal: Principal) -> LockInfo:
        self._require_worker(item_id, principal)
        item = await self._load(uow, item_id)
        now = self._clock.now()
        if _is_claim_live(item, now):
            raise ItemBusy(item_id)
        if is_lock_live(item, now):
            if item.lock_owner != principal.subject:
                held = _info_of(item)
                raise LockConflict(item_id, held.owner_name, held.acquired_at)
            return await self._extend(uow, item, principal, now)
        info = await self._take(uow, item, principal, now)
        await self._history(uow, item_id, principal, "acquire", info.expires_at)
        return info

    async def renew(self, uow: UnitOfWork, item_id: int, principal: Principal) -> LockInfo:
        item = await self._load(uow, item_id)
        now = self._clock.now()
        if item.lock_owner is None or item.lock_owner != principal.subject:
            raise LockNotHeld(item_id)
        if is_lock_live(item, now):
            return await self._extend(uow, item, principal, now)
        if _is_claim_live(item, now):
            raise ItemBusy(item_id)
        info = await self._take(uow, item, principal, now)
        await self._history(uow, item_id, principal, "renew_after_expiry", info.expires_at)
        return info

    async def release(
        self, uow: UnitOfWork, item_id: int, principal: Principal, *, redrive: bool = True
    ) -> None:
        item = await self._load(uow, item_id)
        if item.lock_owner is None:
            return
        if item.lock_owner != principal.subject:
            raise LockNotHeld(item_id)
        now = self._clock.now()
        await uow.repo(ItemLockRepository).clear_lock(item, now=now)
        await self._history(uow, item_id, principal, "release", None)
        if redrive and item.state == ItemState.PENDING:
            # The runner may have skipped (and acknowledged) the event while the lock was held.
            # Resolved at call time: the events module (s03) is built alongside this one.
            events = importlib.import_module("cashapp.pipeline.events")
            event = events.StageEvent.new(item.id, item.stage, clock=self._clock)
            await events.emit(uow, event, item.priority, clock=self._clock)

    async def force_take(
        self, uow: UnitOfWork, item_id: int, principal: Principal, reason: str
    ) -> LockInfo:
        self._require_worker(item_id, principal)
        cleaned = reason.strip()
        if not cleaned:
            raise LockReasonRequired(item_id)
        item = await self._load(uow, item_id)
        now = self._clock.now()
        if _is_claim_live(item, now):
            raise ItemBusy(item_id)
        previous: dict[str, Any] = {
            "previous_owner": item.lock_owner,
            "previous_owner_name": item.lock_owner_name,
            "previous_expires_at": (
                item.lock_expires_at.isoformat() if item.lock_expires_at is not None else None
            ),
        }
        info = await self._take(uow, item, principal, now)
        await self._history(
            uow,
            item_id,
            principal,
            "force_take",
            info.expires_at,
            reasoning=cleaned,
            extra=previous,
        )
        return info

    async def get(self, uow: UnitOfWork, item_id: int) -> LockInfo | None:
        item = await uow.repo(ItemLockRepository).get(item_id)
        if item is None:
            raise ItemNotFound(item_id)
        return lock_info_for(item, self._clock.now())
