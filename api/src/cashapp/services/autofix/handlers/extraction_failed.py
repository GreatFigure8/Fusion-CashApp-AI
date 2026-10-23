"""EXTRACTION_FAILED and LLM_REFUSAL: re-run only the readers that failed, up to the limit."""

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import Stage
from cashapp.pipeline.failures import Escalate, FailureDecision, Reroute
from cashapp.services.autofix.engine import FixContext
from cashapp.services.autofix.hints import bump_effort, failed_readers, replace_fix_hints

_READING_STAGES = frozenset({Stage.EXTRACT, Stage.ADJUDICATE})


class RerunFailedReadersHandler:
    async def decide(self, ctx: FixContext) -> FailureDecision:
        # A classify refusal must not skip classification by jumping to extraction.
        if ctx.error.code == ErrorCode.LLM_REFUSAL and ctx.item.stage not in _READING_STAGES:
            return Escalate(None)
        readers = await failed_readers(ctx.uow, ctx.item, ctx.error)
        effort = bump_effort(ctx.config.models().reader_a.effort)
        replace_fix_hints(ctx.item, {"rerun_readers": readers, "effort": effort})
        names = " and ".join(f"Reader {slot}" for slot in readers)
        ctx.explain(f"{names} did not give a usable reading; re-running {names} only.")
        return Reroute(Stage.EXTRACT)
