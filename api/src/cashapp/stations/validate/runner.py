"""The validate station: load the latest adjudication, run the pure checks, apply the result.

No LLM and no Fusion. On any blocking issue the station raises a typed ``StageError`` and s03
rolls the transaction back, so the item keeps its previous header fields.
"""

from typing import ClassVar

from pydantic import ValidationError

from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.stages import Stage
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container, RoleSpec, Runnable
from cashapp.pipeline.runner import StageConsumer, StageContext, StageRunner
from cashapp.services.validation import first_error, validate

_PAYER_NAME_MAX = 500


class ValidateRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.VALIDATE

    async def process(self, ctx: StageContext) -> StageOutcome:
        item = ctx.item
        adjudication = await ctx.uow.repo(AdjudicationRepository).latest_for(item.id)
        if adjudication is None or adjudication.final is None:
            raise StageError(ErrorCode.EXTRACTION_FAILED, detail={"reason": "no_adjudication"})
        try:
            extraction = RemittanceExtraction.model_validate(adjudication.final)
        except ValidationError as exc:
            raise StageError(
                ErrorCode.EXTRACTION_FAILED,
                detail={
                    "reason": "final_invalid",
                    "adjudication_id": adjudication.id,
                    # Locations and types only: never the input values.
                    "errors": [
                        {"loc": ".".join(str(p) for p in err["loc"]), "type": err["type"]}
                        for err in exc.errors(include_input=False, include_context=False)
                    ],
                },
            ) from exc

        report = validate(extraction, ctx.clock.now().date())
        code = first_error(report)
        if code is not None:
            raise StageError(
                code,
                detail=report.to_detail(),
                message=f"validation failed: {len(report.errors)} issue(s)",
            )

        merged = list(item.info_flags or [])
        for flag in sorted(report.flags, key=lambda f: f.value):
            if flag.value not in merged:
                merged.append(flag.value)
        item.info_flags = merged
        item.payment_amount = extraction.payment_amount.value
        if report.currency is not None:
            item.currency = report.currency
        item.payment_date = extraction.payment_date.value
        payer = extraction.payer_name.value
        if payer:
            item.payer_name = payer[:_PAYER_NAME_MAX]

        flags = ",".join(sorted(f.value for f in report.flags))
        return Advance(
            Stage.RESOLVE_CUSTOMER,
            note=(
                f"validated: {len(report.cleaned.lines)} lines kept, "
                f"{len(report.notices)} zero lines dropped, flags=[{flags}]"
            ),
            payload=report.to_history_payload(adjudication_id=adjudication.id),
        )


def build(container: Container) -> Runnable:
    return StageConsumer(
        ValidateRunner.build(container),
        container.bus,
        container.settings.streaming.consumer_group,
        name="validate",
    )


ROLE = RoleSpec("validate", "consumer", build)
