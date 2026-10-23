"""Caps concurrent Fusion applies per receipt.

In-process only; cross-process exclusivity comes from the receipt reservation in the database.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from cashapp.services.config import RuntimeConfig


class _Slot:
    __slots__ = ("active", "condition", "waiters")

    def __init__(self) -> None:
        self.active = 0
        self.waiters = 0
        self.condition = asyncio.Condition()


class ReceiptApplyGate:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._slots: dict[int, _Slot] = {}

    def active(self, receipt_id: int) -> int:
        slot = self._slots.get(receipt_id)
        return slot.active if slot is not None else 0

    def slot(self, receipt_id: int) -> AbstractAsyncContextManager[None]:
        return self._slot(receipt_id)

    @asynccontextmanager
    async def _slot(self, receipt_id: int) -> AsyncGenerator[None]:
        slot = self._slots.get(receipt_id)
        if slot is None:
            slot = self._slots[receipt_id] = _Slot()
        slot.waiters += 1
        acquired = False
        try:
            async with slot.condition:
                while True:
                    # Re-read on every attempt so a changed limit applies to the next waiter.
                    limit = (await self._config.concurrency()).apply_per_receipt
                    if slot.active < limit:
                        break
                    await slot.condition.wait()
                slot.active += 1
                acquired = True
        finally:
            slot.waiters -= 1
            if not acquired:
                self._cleanup(receipt_id, slot)
        try:
            yield
        finally:
            slot.active -= 1
            self._cleanup(receipt_id, slot)
            async with slot.condition:
                slot.condition.notify_all()

    def _cleanup(self, receipt_id: int, slot: _Slot) -> None:
        if slot.active == 0 and slot.waiters == 0 and self._slots.get(receipt_id) is slot:
            del self._slots[receipt_id]
