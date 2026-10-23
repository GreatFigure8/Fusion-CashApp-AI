"""Chat tools for the processing engine (group ENGINE): read the engine, pause / resume / drain a
station, set concurrency, replay dead letters.

Every handler calls the same ``EngineService`` method the router calls, so the audit row is the
same apart from ``source``. Mutating tools are confirm-required: the preview shows before, after
and the in-flight count; the person types the reason at confirm; a stale ``expected_version`` is a
conflict that changes nothing. Written against the registry contract of chat-agent-tool-registry.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from cashapp.services.chat.tools.cards import CardStat, CardStatus, ResultCard, StateCard
from cashapp.services.chat.tools.registry import (
    ConfirmPreview,
    PreviewField,
    ToolContext,
    ToolError,
    ToolGroup,
    ToolSpec,
    who_line,
)
from pydantic import BaseModel, Field

from cashapp.api.schemas.engine import EngineActionOut, EngineStatusOut, ReplayOut, StationName
from cashapp.domain.engine import EngineAction, Station
from cashapp.domain.principal import Permission
from cashapp.services.config import ConfigConflict, ConfigError
from cashapp.services.engine import text
from cashapp.services.engine.models import EnginePreview
from cashapp.services.engine.service import (
    EngineConflict,
    EngineError,
    EngineForbidden,
    EngineReasonRequired,
    EngineService,
    ThrottleOutOfBounds,
)

# --------------------------------------------------------------------------- inputs


class NoInput(BaseModel):
    """engine.status takes no arguments."""


class StationIn(BaseModel):
    station: StationName = Field(
        description="The station to act on. Reader A and reader B share one extract consumer."
    )


class ThrottleToolIn(BaseModel):
    per_stage: int = Field(ge=1, le=32, description="Items worked at once per stage (1 to 32).")
    apply_per_receipt: int = Field(
        ge=1, le=8, description="Fusion applies run at once per receipt (1 to 8)."
    )


class ReplayToolIn(BaseModel):
    event_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
        description="Event ids from the dead-letter list (GET /engine/dead-letters).",
    )


# --------------------------------------------------------------------------- helpers


@asynccontextmanager
async def _engine_errors(tool: str) -> AsyncIterator[None]:
    """Turn the service's errors into the tool errors the chat shows."""
    try:
        yield
    except (EngineConflict, ConfigConflict) as exc:
        raise ToolError(
            "CONFLICT",
            f"{tool} returned 409: the engine settings changed since the preview. Nothing changed.",
            409,
        ) from exc
    except EngineForbidden as exc:
        raise ToolError("FORBIDDEN", str(exc), 403) from exc
    except (EngineReasonRequired, ThrottleOutOfBounds) as exc:
        raise ToolError("INVALID_VALUE", str(exc), 422) from exc
    except (EngineError, ConfigError) as exc:
        raise ToolError("ENGINE_ERROR", str(exc), 400) from exc


def _confirmation(ctx: ToolContext, tool: str) -> tuple[str, int]:
    """The reason and the version the person confirmed; both are required to act."""
    confirmation = ctx.confirmation
    if confirmation is None or confirmation.expected_version is None:
        raise ToolError(
            "INVALID_VALUE", f"{tool} needs a confirmed reason and engine version.", 422
        )
    return confirmation.reason, confirmation.expected_version


def _to_confirm(ctx: ToolContext, preview: EnginePreview) -> ConfirmPreview:
    return ConfirmPreview(
        what=preview.what,
        before=preview.before,
        after=preview.after,
        who=who_line(ctx.principal),
        expected_version=preview.expected_version,
        details=[PreviewField(label=label, value=value) for label, value in preview.details],
    )


def _status_card(out: EngineStatusOut) -> ResultCard | None:
    states = out.counts
    held = states["paused"] + states["draining"] + states["drained"]
    tone = "ok" if out.bus_healthy and not states["paused"] else "warn"
    return StateCard(
        title="Processing engine",
        status=CardStatus(
            label=f"{states['running']} running, {held} held",
            tone=tone,
        ),
        stats=[
            CardStat(label="Total lag", value=str(out.total_lag)),
            CardStat(label="Dead letters", value=str(out.dlq_total)),
            CardStat(label="Bus", value="healthy" if out.bus_healthy else "unhealthy"),
        ],
    )


def _action_card(out: EngineActionOut) -> ResultCard | None:
    audit = out.audit
    where = ", ".join(audit.stations) if audit.stations else "engine"
    return StateCard(
        title=f"{audit.action.capitalize()}: {where}",
        status=CardStatus(label="Done", tone="ok"),
        stats=[
            CardStat(label="Engine version", value=str(audit.config_version)),
            CardStat(label="By", value=audit.actor_name),
        ],
    )


def _replay_card(out: ReplayOut) -> ResultCard | None:
    return StateCard(
        title="Dead letters replayed",
        status=CardStatus(label=f"{out.replayed} replayed", tone="ok" if out.replayed else "muted"),
        stats=[CardStat(label="Skipped", value=str(len(out.skipped)))],
    )


def _station_of(inp: StationIn) -> Station:
    return Station(inp.station)


# --------------------------------------------------------------------------- handlers


async def _status(ctx: ToolContext, _: NoInput) -> EngineStatusOut:
    service = await ctx.services.get(EngineService)
    return EngineStatusOut.from_data(await service.status())


async def _pause(ctx: ToolContext, inp: StationIn) -> EngineActionOut:
    reason, version = _confirmation(ctx, "engine.pause")
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.pause"):
        result = await service.pause(
            _station_of(inp), reason, version, ctx.principal, source="chat"
        )
    return EngineActionOut.from_data(result)


async def _resume(ctx: ToolContext, inp: StationIn) -> EngineActionOut:
    reason, version = _confirmation(ctx, "engine.resume")
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.resume"):
        result = await service.resume(
            _station_of(inp), reason, version, ctx.principal, source="chat"
        )
    return EngineActionOut.from_data(result)


async def _drain(ctx: ToolContext, inp: StationIn) -> EngineActionOut:
    reason, version = _confirmation(ctx, "engine.drain")
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.drain"):
        result = await service.drain(
            _station_of(inp), reason, version, ctx.principal, source="chat"
        )
    return EngineActionOut.from_data(result)


async def _set_throttle(ctx: ToolContext, inp: ThrottleToolIn) -> EngineActionOut:
    reason, version = _confirmation(ctx, "engine.set_throttle")
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.set_throttle"):
        result = await service.set_throttle(
            inp.per_stage, inp.apply_per_receipt, reason, version, ctx.principal, source="chat"
        )
    return EngineActionOut.from_data(result)


async def _replay(ctx: ToolContext, inp: ReplayToolIn) -> ReplayOut:
    reason, _ = _confirmation(ctx, "engine.replay_dead_letters")
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.replay_dead_letters"):
        result = await service.replay_dead_letters(
            inp.event_ids, reason, ctx.principal, source="chat"
        )
    return ReplayOut.from_data(result)


# --------------------------------------------------------------------------- previews


def _station_preview(action: EngineAction) -> Any:
    async def preview(ctx: ToolContext, inp: StationIn) -> ConfirmPreview:
        service = await ctx.services.get(EngineService)
        async with _engine_errors(f"engine.{action.value.lower()}"):
            return _to_confirm(ctx, await service.preview(action, [_station_of(inp)]))

    return preview


async def _throttle_preview(ctx: ToolContext, inp: ThrottleToolIn) -> ConfirmPreview:
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.set_throttle"):
        return _to_confirm(
            ctx,
            await service.preview(
                EngineAction.THROTTLE,
                [],
                per_stage=inp.per_stage,
                apply_per_receipt=inp.apply_per_receipt,
            ),
        )


async def _replay_preview(ctx: ToolContext, inp: ReplayToolIn) -> ConfirmPreview:
    service = await ctx.services.get(EngineService)
    async with _engine_errors("engine.replay_dead_letters"):
        return _to_confirm(
            ctx, await service.preview(EngineAction.REPLAY, [], event_ids=inp.event_ids)
        )


# --------------------------------------------------------------------------- the tools

TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="engine.status",
        group=ToolGroup.ENGINE,
        description=text.TOOL_DESC_STATUS,
        input_model=NoInput,
        output_model=EngineStatusOut,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Read the engine status",
        handler=_status,
        card=_status_card,
        summarize_output=lambda out: (
            f"{out.counts['running']} stations running, lag {out.total_lag}, "
            f"{out.dlq_total} dead letters"
        ),
    ),
    ToolSpec(
        name="engine.pause",
        group=ToolGroup.ENGINE,
        description=text.TOOL_DESC_PAUSE,
        input_model=StationIn,
        output_model=EngineActionOut,
        permission=Permission.ENGINE_CONTROL,
        mutating=True,
        confirm_required=True,
        audit_label="Paused a station",
        handler=_pause,
        preview=_station_preview(EngineAction.PAUSE),
        card=_action_card,
        summarize_input=lambda inp: f"pause {inp.station}",
    ),
    ToolSpec(
        name="engine.resume",
        group=ToolGroup.ENGINE,
        description=text.TOOL_DESC_RESUME,
        input_model=StationIn,
        output_model=EngineActionOut,
        permission=Permission.ENGINE_CONTROL,
        mutating=True,
        confirm_required=True,
        audit_label="Resumed a station",
        handler=_resume,
        preview=_station_preview(EngineAction.RESUME),
        card=_action_card,
        summarize_input=lambda inp: f"resume {inp.station}",
    ),
    ToolSpec(
        name="engine.drain",
        group=ToolGroup.ENGINE,
        description=text.TOOL_DESC_DRAIN,
        input_model=StationIn,
        output_model=EngineActionOut,
        permission=Permission.ENGINE_CONTROL,
        mutating=True,
        confirm_required=True,
        audit_label="Drained a station",
        handler=_drain,
        preview=_station_preview(EngineAction.DRAIN),
        card=_action_card,
        summarize_input=lambda inp: f"drain {inp.station}",
    ),
    ToolSpec(
        name="engine.set_throttle",
        group=ToolGroup.ENGINE,
        description=text.TOOL_DESC_THROTTLE,
        input_model=ThrottleToolIn,
        output_model=EngineActionOut,
        permission=Permission.ENGINE_CONTROL,
        mutating=True,
        confirm_required=True,
        audit_label="Changed engine concurrency",
        handler=_set_throttle,
        preview=_throttle_preview,
        card=_action_card,
        summarize_input=lambda inp: (
            f"{inp.per_stage} per stage, {inp.apply_per_receipt} applies per receipt"
        ),
    ),
    ToolSpec(
        name="engine.replay_dead_letters",
        group=ToolGroup.ENGINE,
        description=text.TOOL_DESC_REPLAY,
        input_model=ReplayToolIn,
        output_model=ReplayOut,
        permission=Permission.ENGINE_CONTROL,
        mutating=True,
        confirm_required=True,
        audit_label="Replayed dead letters",
        handler=_replay,
        preview=_replay_preview,
        card=_replay_card,
        summarize_input=lambda inp: f"replay {len(inp.event_ids)} dead letters",
    ),
]
