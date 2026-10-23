"""Matching lab chat tools: propose, replay, promote and discard a matching-config candidate.

Written against the pinned registry contract (chat-agent-tool-registry plan section 7). Every
tool calls the same ``LabService`` the router calls, so an audited promote looks the same from
either door. The tool and field descriptions are prompt surface: the model reads them.
"""

import asyncio
import contextlib
from typing import Any, Final

from pydantic import BaseModel, Field, JsonValue

from cashapp.domain import config_keys as ck
from cashapp.domain.lab import ReplayStatus
from cashapp.domain.principal import Permission
from cashapp.services.chat.tools.cards import ReplayCard, ReplayCurrency
from cashapp.services.chat.tools.registry import (
    ConfirmPreview,
    DiffLine,
    PreviewField,
    ToolContext,
    ToolError,
    ToolGroup,
    ToolSpec,
    who_line,
)
from cashapp.services.config import RuntimeConfig
from cashapp.services.lab.errors import LabError
from cashapp.services.lab.service import Candidate, LabService, ReplayResult

_LAB_HREF: Final = "/lab?candidate={candidate}"
_TERMINAL: Final = (ReplayStatus.DONE, ReplayStatus.FAILED, ReplayStatus.STALE)


def _tool_error(exc: LabError) -> ToolError:
    return ToolError(exc.code, exc.message, exc.status)


# --------------------------------------------------------------------------- schemas


class DiffRowOut(BaseModel):
    key: str
    before: JsonValue
    after: JsonValue


class LabProposeIn(BaseModel):
    changes: dict[str, JsonValue] = Field(
        description=(
            "The matching settings to try, as {key: new value}. Only matching.date_window_days, "
            "matching.tolerances, matching.bank_fee_bands, matching.scorer_weights and "
            "matching.min_score are allowed. Give each key's complete new value."
        ),
        min_length=1,
    )
    rationale: str = Field(
        description="Why this change is worth trying, in one or two sentences.", max_length=2000
    )


class LabCandidateCard(BaseModel):
    candidate_id: str
    base_version: int
    config_diff: list[DiffRowOut]


class LabReplayIn(BaseModel):
    candidate_id: str = Field(description="The candidate id, like p_0001.")
    window_days: int | None = Field(
        default=None,
        description="How many days of past items to replay. Leave empty for the default.",
    )


class LabReplayMoney(BaseModel):
    currency: str
    newly_matched: str
    newly_unmatched: str
    items: int


class LabReplayOut(BaseModel):
    replay_id: str
    candidate_id: str
    status: ReplayStatus
    done: int
    total: int
    changed: int
    newly_matched: int
    newly_failed: int
    newly_ambiguous: int
    money_by_currency: list[LabReplayMoney]
    stale_message: str | None = None


class LabPromoteIn(BaseModel):
    candidate_id: str = Field(description="The candidate to make live, like p_0001.")
    replay_id: str = Field(description="A finished replay of that candidate, like rp_0001.")


class LabPromoteOut(BaseModel):
    candidate_id: str
    replay_id: str
    new_version: int
    keys: list[str]


class LabDiscardIn(BaseModel):
    candidate_id: str = Field(description="The candidate to close without making it live.")


class LabDiscardOut(BaseModel):
    candidate_id: str
    status: str


# --------------------------------------------------------------------------- helpers


def _replay_out(result: ReplayResult) -> LabReplayOut:
    return LabReplayOut(
        replay_id=result.id,
        candidate_id=result.candidate_id,
        status=result.status,
        done=result.done,
        total=result.total,
        changed=result.changed,
        newly_matched=result.newly_matched,
        newly_failed=result.newly_failed,
        newly_ambiguous=result.newly_ambiguous,
        money_by_currency=[
            LabReplayMoney(
                currency=m.currency,
                newly_matched=m.newly_matched,
                newly_unmatched=m.newly_unmatched,
                items=m.items,
            )
            for m in result.money_by_currency
        ],
        stale_message=result.stale_message,
    )


def _diff_lines(candidate: Candidate) -> list[DiffLine]:
    lines: list[DiffLine] = []
    for row in candidate.config_diff:
        lines.append(DiffLine(op="-", text=f"{row.key}: {row.before}"))
        lines.append(DiffLine(op="+", text=f"{row.key}: {row.after}"))
    return lines


# --------------------------------------------------------------------------- handlers


async def _propose(ctx: ToolContext, args: LabProposeIn) -> LabCandidateCard:
    service = await ctx.services.get(LabService)
    try:
        candidate = await service.create_candidate(args.changes, args.rationale, ctx.principal)
    except LabError as exc:
        raise _tool_error(exc) from exc
    return LabCandidateCard(
        candidate_id=candidate.id,
        base_version=candidate.base_version,
        config_diff=[
            DiffRowOut(key=d.key, before=d.before, after=d.after) for d in candidate.config_diff
        ],
    )


async def _replay(ctx: ToolContext, args: LabReplayIn) -> LabReplayOut:
    service = await ctx.services.get(LabService)
    wait = await _chat_wait(ctx)
    try:
        started = await service.replay(args.candidate_id, args.window_days, ctx.principal)
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(wait):
                async for event in service.stream(started.id, ctx.principal):
                    done, total = event.data.get("done"), event.data.get("total")
                    if isinstance(done, int) and isinstance(total, int):
                        await ctx.progress(done, total)
                    if event.terminal:
                        break
        return _replay_out(await service.get_replay(started.id, ctx.principal))
    except LabError as exc:
        raise _tool_error(exc) from exc


async def _chat_wait(ctx: ToolContext) -> float:
    runtime = await ctx.services.get(RuntimeConfig)
    return float(await runtime.get(ck.LAB_CHAT_WAIT_SECONDS))


async def _promote(ctx: ToolContext, args: LabPromoteIn) -> LabPromoteOut:
    confirmation = ctx.confirmation
    if confirmation is None or confirmation.expected_version is None:
        raise ToolError("INVALID_VALUE", "Promote needs a confirmation with the version", 422)
    service = await ctx.services.get(LabService)
    try:
        promotion = await service.promote(
            args.candidate_id,
            args.replay_id,
            confirmation.reason,
            confirmation.expected_version,
            ctx.principal,
        )
    except LabError as exc:
        raise _tool_error(exc) from exc
    return LabPromoteOut(
        candidate_id=promotion.candidate_id,
        replay_id=promotion.replay_id,
        new_version=promotion.new_version,
        keys=promotion.keys,
    )


async def _promote_preview(ctx: ToolContext, args: LabPromoteIn) -> ConfirmPreview:
    service = await ctx.services.get(LabService)
    try:
        candidate = await service.get_candidate(args.candidate_id, ctx.principal)
        replay = await service.get_replay(args.replay_id, ctx.principal)
    except LabError as exc:
        raise _tool_error(exc) from exc
    live = candidate.live_version
    return ConfirmPreview(
        what=f"Promote {candidate.id} to live",
        before=f"Live matching config v{live}",
        after=f"v{live + 1} with {len(candidate.changes)} setting(s) changed",
        who=who_line(ctx.principal),
        expected_version=live,
        details=[
            PreviewField(label="Rationale", value=candidate.rationale),
            PreviewField(
                label="Replay",
                value=(
                    f"{replay.id}: {replay.changed} changed, {replay.newly_matched} newly "
                    f"matched, {replay.newly_failed} newly failed, "
                    f"{replay.newly_ambiguous} newly ambiguous"
                ),
            ),
            PreviewField(label="Expected version", value=f"v{live}"),
        ],
        diff=_diff_lines(candidate),
    )


async def _discard(ctx: ToolContext, args: LabDiscardIn) -> LabDiscardOut:
    service = await ctx.services.get(LabService)
    reason = ctx.confirmation.reason if ctx.confirmation is not None else None
    try:
        candidate = await service.discard(args.candidate_id, ctx.principal, reason)
    except LabError as exc:
        raise _tool_error(exc) from exc
    return LabDiscardOut(candidate_id=candidate.id, status=candidate.status.value)


async def _discard_preview(ctx: ToolContext, args: LabDiscardIn) -> ConfirmPreview:
    service = await ctx.services.get(LabService)
    try:
        candidate = await service.get_candidate(args.candidate_id, ctx.principal)
    except LabError as exc:
        raise _tool_error(exc) from exc
    return ConfirmPreview(
        what=f"Discard {candidate.id}",
        before="Open candidate",
        after="Discarded; live config is untouched",
        who=who_line(ctx.principal),
        details=[PreviewField(label="Rationale", value=candidate.rationale)],
        diff=_diff_lines(candidate),
    )


# --------------------------------------------------------------------------- cards


def _replay_card(out: LabReplayOut) -> ReplayCard | None:
    number = out.candidate_id
    return ReplayCard(
        candidate_id=number,
        replay_id=out.replay_id,
        status=out.status.value,  # type: ignore[arg-type]
        changed=out.changed,
        newly_matched=out.newly_matched,
        newly_failed=out.newly_failed,
        newly_ambiguous=out.newly_ambiguous,
        currencies=[ReplayCurrency.model_validate(m.model_dump()) for m in out.money_by_currency],
        lab_href=_LAB_HREF.format(candidate=number) + f"&replay={out.replay_id}",
    )


def _summary_propose(args: LabProposeIn) -> str:
    return f"Propose changes to {', '.join(sorted(args.changes))}"[:200]


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="lab.propose",
        group=ToolGroup.LAB,
        description=(
            "Create a matching-lab candidate: a proposed change to the matching settings that "
            "is kept apart from live config. It changes nothing live. Follow it with "
            "lab.replay to see its effect on past items."
        ),
        input_model=LabProposeIn,
        output_model=LabCandidateCard,
        permission=Permission.LAB_RUN,
        mutating=False,
        confirm_required=False,
        audit_label="lab.propose",
        handler=_propose,
        summarize_input=_summary_propose,
    ),
    ToolSpec(
        name="lab.replay",
        group=ToolGroup.LAB,
        description=(
            "Replay a candidate against past items and report how many would newly match, "
            "newly fail or become ambiguous versus live config. Read-only: nothing is written "
            "to Fusion. May return a still-running result if it takes long."
        ),
        input_model=LabReplayIn,
        output_model=LabReplayOut,
        permission=Permission.LAB_RUN,
        mutating=False,
        confirm_required=False,
        audit_label="lab.replay",
        handler=_replay,
        card=_replay_card,
        timeout_s=660.0,
    ),
    ToolSpec(
        name="lab.promote",
        group=ToolGroup.LAB,
        description=(
            "Make a candidate live after a finished replay. Changes the live matching "
            "settings, so the person must confirm with a reason."
        ),
        input_model=LabPromoteIn,
        output_model=LabPromoteOut,
        permission=Permission.CONFIG_WRITE,
        mutating=True,
        confirm_required=True,
        audit_label="lab.promote",
        handler=_promote,
        preview=_promote_preview,
    ),
    ToolSpec(
        name="lab.discard",
        group=ToolGroup.LAB,
        description="Close a candidate without making it live. Live config is untouched.",
        input_model=LabDiscardIn,
        output_model=LabDiscardOut,
        permission=Permission.LAB_RUN,
        mutating=True,
        confirm_required=True,
        audit_label="lab.discard",
        handler=_discard,
        preview=_discard_preview,
    ),
]
