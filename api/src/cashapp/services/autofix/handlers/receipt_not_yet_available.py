"""RECEIPT_NOT_YET_AVAILABLE: wait for the receipt instead of failing."""

from cashapp.pipeline.failures import FailureDecision, ParkAwaitingReceipt
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.hints import replace_fix_hints


class ParkAwaitingReceiptHandler:
    """Park the item; the receipt watcher wakes it. Also try the receipt creation date."""

    async def decide(self, ctx: FixContext) -> FailureDecision:
        replace_fix_hints(ctx.item, {"match_on_creation_date": True})
        if ctx.item.awaiting_since is None:
            ctx.item.awaiting_since = ctx.clock.now()
        ctx.explain(
            "No matching receipt in Fusion yet; waiting for it to arrive and will also match "
            "on receipt creation date."
        )
        return ParkAwaitingReceipt()
