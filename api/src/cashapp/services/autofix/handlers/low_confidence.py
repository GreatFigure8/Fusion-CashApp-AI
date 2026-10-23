"""LOW_EXTRACTION_CONFIDENCE: re-run the readers at higher effort once."""

from cashapp.pipeline.failures import FailureDecision
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.handlers.reextract import reextract_once


class LowConfidenceHandler:
    async def decide(self, ctx: FixContext) -> FailureDecision:
        return reextract_once(ctx)
