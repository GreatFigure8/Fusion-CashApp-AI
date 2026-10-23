"""Escalate: for codes with no automatic fix (the engine writes the summary)."""

from cashapp.pipeline.failures import Escalate, FailureDecision
from cashapp.services.autofix.engine import FixContext


class EscalateHandler:
    """AMOUNT_VARIANCE, the always-person codes and every code without its own handler."""

    async def decide(self, ctx: FixContext) -> FailureDecision:
        return Escalate(None)
