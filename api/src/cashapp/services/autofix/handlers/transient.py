"""Transient failures: retry the same stage after a configured backoff."""

from datetime import timedelta

from cashapp.pipeline.failures import FailureDecision, Retry
from cashapp.services.autofix.engine import FixContext


class BackoffRetryHandler:
    """FUSION_LOCKED, FUSION_TRANSIENT and LLM_TRANSIENT. Hints are left unchanged."""

    async def decide(self, ctx: FixContext) -> FailureDecision:
        attempt = ctx.attempts_for_code + 1
        seconds = ctx.config.retries().backoff_for(attempt)
        ctx.explain(f"Transient failure; retry {attempt}/{ctx.limit} in {seconds} s.")
        return Retry(after=timedelta(seconds=seconds))
