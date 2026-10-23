"""RECEIPT_AMBIGUOUS: re-match once with references and dates before asking a person."""

from cashapp.domain.stages import Stage
from cashapp.pipeline.failures import Escalate, FailureDecision, Reroute
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.hints import replace_fix_hints


class NarrowReceiptHandler:
    async def decide(self, ctx: FixContext) -> FailureDecision:
        if ctx.attempts_for_code >= 1:
            return Escalate(None)
        replace_fix_hints(ctx.item, {"narrow": True})
        count = ctx.error.detail.get("candidates")
        if isinstance(count, int) and not isinstance(count, bool):
            lead = f"{count} receipts qualified"
        else:
            lead = "More than one receipt qualified"
        ctx.explain(f"{lead}; re-matching with references and dates to narrow.")
        return Reroute(Stage.MATCH_RECEIPT)
