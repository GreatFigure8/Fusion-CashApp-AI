"""FUSION_GL_DATE: apply again no earlier than the receipt's GL date."""

from datetime import date

from cashapp.domain.stages import Stage
from cashapp.pipeline.failures import Escalate, FailureDecision, Reroute
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.hints import replace_fix_hints


def _iso_date(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


class GlDateFloorHandler:
    async def decide(self, ctx: FixContext) -> FailureDecision:
        floor = _iso_date(ctx.error.detail.get("receipt_gl_date"))
        if floor is None:
            return Escalate(None)
        replace_fix_hints(ctx.item, {"gl_date_floor": floor})
        ctx.explain(
            f"Accounting date was before the receipt GL date; re-dating to {floor} or later."
        )
        return Reroute(Stage.APPLY)
