"""Not-found style codes: read the remittance again at higher effort, once, never a plain retry."""

from cashapp.domain.stages import Stage
from cashapp.pipeline.failures import Escalate, FailureDecision, Reroute
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.hints import bump_effort, replace_fix_hints


def reextract_once(ctx: FixContext) -> FailureDecision:
    """Reroute to EXTRACT with both readers at the next effort level; escalate on a repeat."""
    if ctx.attempts_for_code >= 1:
        return Escalate(None)
    effort = bump_effort(ctx.config.models().reader_a.effort)
    replace_fix_hints(ctx.item, {"rerun_readers": ["A", "B"], "effort": effort})
    ctx.explain("Re-reading the remittance at higher effort before trying again.")
    return Reroute(Stage.EXTRACT)


class ReExtractHandler:
    """CUSTOMER_NOT_FOUND, INVOICE_NOT_FOUND and INVALID_INVOICE_NUMBER."""

    async def decide(self, ctx: FixContext) -> FailureDecision:
        return reextract_once(ctx)
