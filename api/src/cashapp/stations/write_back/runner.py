"""The write-back station: attach the remittance and note the outcome on the Fusion receipt.

A failure here raises ``StageError(WRITE_BACK_FAILED)`` and never touches ``APPLICATION_LEDGER``
or ``LINE_RESULT``: the applications already made in Fusion stand. FUSION_WRITE history rows
committed by ``write_back`` survive the runner's rollback.
"""

from typing import ClassVar, Self

from cashapp.domain.config_keys import FUSION_RECEIPT_NOTE_MAX_CHARS
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Finish, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.write_back import (
    WriteBackDeps,
    receipts_for_write_back,
    write_back,
)


class WriteBackRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.WRITE_BACK

    def __init__(self, deps: RunnerDeps, *, write_back_deps: WriteBackDeps) -> None:
        super().__init__(deps)
        self._write_back_deps = write_back_deps

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(
            RunnerDeps.from_container(container),
            write_back_deps=WriteBackDeps.from_container(container),
        )

    async def process(self, ctx: StageContext) -> StageOutcome:
        item = ctx.item
        if item.payment_status is None:
            raise StageError(
                ErrorCode.WRITE_BACK_FAILED,
                detail={"cause": "PAYMENT_STATUS_MISSING", "retryable": False},
            )
        receipts = await receipts_for_write_back(ctx.uow, item.id)
        if not receipts:
            await record_history(
                ctx.uow,
                item.id,
                HistoryEntry(
                    action=HistoryAction.DECISION,
                    reasoning="No receipt to write back to; nothing written in Fusion.",
                ),
                clock=ctx.clock,
            )
            return Finish(item.payment_status, note="write-back skipped: no receipt")

        max_chars = ctx.config.get(FUSION_RECEIPT_NOTE_MAX_CHARS)
        attachments: list[str] = []
        notes: list[str] = []
        for receipt_id in receipts:
            result = await write_back(
                ctx.uow,
                item,
                receipt_id,
                mode="applied",
                deps=self._write_back_deps,
                note_max_chars=max_chars,
                clock=ctx.clock,
            )
            if result.attachment_ref is None:
                attachments.append("skipped")
            else:
                attachments.append("reused" if result.attachment_reused else "added")
            notes.append("present" if result.note_already_present else "written")
        ctx.log.info(
            "write-back done",
            extra={"receipts": len(receipts), "attachments": attachments, "notes": notes},
        )
        return Finish(
            item.payment_status,
            note=f"write-back done: attachment {','.join(attachments)}, note {','.join(notes)}",
        )


ROLE = consumer_role(WriteBackRunner, "write-back")
build = ROLE.build
