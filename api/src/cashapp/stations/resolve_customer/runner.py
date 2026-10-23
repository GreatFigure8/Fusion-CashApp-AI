"""The resolve-customer station: ties the extracted remittance to its Fusion customer account.

Everything happens in the runner's own transaction: the resolution row, the work-item update and
the DECISION history row are committed together with the transition to FAST_PATH, or not at all.
"""

from collections.abc import Callable
from typing import Any, ClassVar, Self

from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.customer import CustomerResolution, ResolutionMethod
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.integrations.fusion.client import FusionClient
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.services.aliases import AliasLookup, AliasService
from cashapp.services.customer import resolve_customer
from cashapp.services.history import HistoryEntry, record_history

AliasFactory = Callable[[UnitOfWork], AliasLookup]


def default_alias_lookup(uow: UnitOfWork) -> AliasLookup:
    """The alias service on this unit of work (``lookup`` counts uses, so it must share it)."""
    return AliasService(uow)


def _reasoning(resolution: CustomerResolution) -> str:
    anchor = resolution.anchor_customer_number
    if resolution.method is ResolutionMethod.HUMAN:
        text = f"Anchor customer {anchor} from a person's choice at requeue, which was honoured"
    elif resolution.method is ResolutionMethod.ALIAS:
        ids = ", ".join(str(i) for i in resolution.alias_ids)
        text = f"Anchor customer {anchor} from payer alias {ids}"
    else:
        finding = next(
            (f for f in resolution.line_findings if f.line_no == resolution.anchor_line_no), None
        )
        number = finding.transaction_number if finding is not None else "?"
        text = (
            f"Anchor customer {anchor} from invoice {number} "
            f"(line {resolution.anchor_line_no}, first line whose transaction was found)"
        )
    related = len(resolution.related_customer_numbers)
    text += f"; {related} related account{'s' if related != 1 else ''} widen the receipt search"
    if resolution.currency is not None:
        text += f"; currency {resolution.currency} from {_source_text(resolution)}"
    return text + "."


def _source_text(resolution: CustomerResolution) -> str:
    return {
        "extraction": "the extraction",
        "customer": "the customer account",
        "anchor_transactions": "the anchor's transactions",
    }.get(resolution.currency_source or "", "the extraction")


def _payload(resolution: CustomerResolution, resolution_id: int) -> dict[str, Any]:
    anchor_number = next(
        (
            f.transaction_number
            for f in resolution.line_findings
            if f.line_no == resolution.anchor_line_no
        ),
        None,
    )
    return {
        "method": resolution.method.value,
        "anchor_customer_number": resolution.anchor_customer_number,
        "anchor_line_no": resolution.anchor_line_no,
        "anchor_transaction_number": anchor_number,
        "alias_ids": list(resolution.alias_ids),
        "related_customer_numbers": list(resolution.related_customer_numbers),
        "currency": resolution.currency,
        "currency_source": resolution.currency_source,
        "flags": sorted(f.value for f in resolution.flags),
        "line_findings": [
            {
                "line_no": f.line_no,
                "transaction_number": f.transaction_number,
                "status": f.status.value,
                "candidate_status": f.candidate_status.value if f.candidate_status else None,
            }
            for f in resolution.line_findings
        ],
        "transactions_found": len(resolution.transactions),
        "resolution_id": resolution_id,
    }


class ResolveCustomerRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.RESOLVE_CUSTOMER

    def __init__(
        self,
        deps: RunnerDeps,
        *,
        fusion: FusionClient,
        alias_factory: AliasFactory = default_alias_lookup,
    ) -> None:
        super().__init__(deps)
        self._fusion = fusion
        self._alias_factory = alias_factory

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(RunnerDeps.from_container(container), fusion=container.resolve(FusionClient))

    async def process(self, ctx: StageContext) -> StageOutcome:
        uow, item = ctx.uow, ctx.item
        adjudication = await uow.repo(AdjudicationRepository).latest_for(item.id)
        if adjudication is None or adjudication.final is None:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_adjudication"})
        extraction = RemittanceExtraction.model_validate(adjudication.final)

        hint = (item.human_hints or {}).get("customer_number")
        resolution = await resolve_customer(
            extraction,
            aliases=self._alias_factory(uow),
            fusion=self._fusion,
            human_customer_number=hint,
            log=ctx.log,
        )

        row = await uow.repo(CustomerResolutionRepository).add_resolution(
            item.id, resolution, now=ctx.clock.now()
        )
        merged = list(item.info_flags)
        merged.extend(
            flag.value for flag in sorted(resolution.flags) if flag.value not in item.info_flags
        )
        await uow.work_items.update(
            item,
            customer_account_number=resolution.anchor_customer_number,
            currency=resolution.currency or item.currency,
            info_flags=merged,
        )
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.DECISION,
                reasoning=_reasoning(resolution),
                payload=_payload(resolution, row.id),
            ),
            clock=ctx.clock,
        )
        ctx.log.info(
            "customer resolved",
            extra={
                "method": resolution.method.value,
                "related_count": len(resolution.related_customer_numbers),
                "transactions_found": len(resolution.transactions),
            },
        )
        return Advance(Stage.FAST_PATH, note="customer resolved", payload={"resolution_id": row.id})


ROLE = consumer_role(ResolveCustomerRunner, "resolve-customer")
build = ROLE.build
