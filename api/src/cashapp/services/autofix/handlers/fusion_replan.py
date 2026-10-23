"""FUSION_OVERAPPLY and FUSION_ALREADY_APPLIED: plan the lines again from fresh Fusion state."""

from cashapp.domain.stages import Stage
from cashapp.pipeline.failures import FailureDecision, Reroute
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.hints import replace_fix_hints


class ReplanLinesHandler:
    """Line matching re-reads balances and existing applications, so it clamps or reconciles."""

    async def decide(self, ctx: FixContext) -> FailureDecision:
        replace_fix_hints(ctx.item, {})
        ctx.explain(
            "Fusion balances or existing applications differ from the plan; re-planning the "
            "lines from fresh Fusion data."
        )
        return Reroute(Stage.MATCH_LINES)
