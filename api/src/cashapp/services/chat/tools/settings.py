"""Settings tools: read the runtime configuration, propose a change (confirmed by the person)."""

import json
from typing import Any

from pydantic import BaseModel, Field

from cashapp.domain.principal import Permission
from cashapp.services.chat.tools.cards import TableCard, TableColumn
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
from cashapp.services.config import (
    ConfigConflict,
    ConfigError,
    ConfigValidationError,
    ConfigWriter,
    RuntimeConfig,
    UnknownConfigKey,
    list_config_entries,
    lookup_key,
    validate_value,
)

VALUE_PREVIEW_MAX = 120


class SettingsReadIn(BaseModel):
    key: str | None = Field(
        default=None, description="One exact setting key, e.g. matching.date_window_days."
    )
    group: str | None = Field(
        default=None, description="Only settings of this group, e.g. matching."
    )


class SettingOut(BaseModel):
    key: str
    group: str
    description: str
    value: Any
    default: Any
    version: int


class SettingsReadOut(BaseModel):
    settings: list[SettingOut]


class ProposeChangeIn(BaseModel):
    key: str = Field(description="The exact setting key to change.")
    value: Any = Field(description="The new value, as JSON, in the same shape as the current one.")


class ProposeChangeOut(BaseModel):
    key: str
    version: int
    value: Any


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, indent=2)


async def _read(ctx: ToolContext, args: SettingsReadIn) -> SettingsReadOut:
    try:
        async with ctx.uow_factory() as uow:
            entries = await list_config_entries(uow, only=args.key)
    except UnknownConfigKey as exc:
        raise ToolError("NOT_FOUND", f"There is no setting named {exc.key!r}.", 404) from exc
    return SettingsReadOut(
        settings=[
            SettingOut(
                key=e.key,
                group=e.group,
                description=e.description,
                value=e.value,
                default=e.default,
                version=e.version,
            )
            for e in entries
            if args.group is None or e.group == args.group
        ]
    )


def _read_card(out: SettingsReadOut) -> TableCard:
    return TableCard(
        title="Settings",
        columns=[
            TableColumn(key="key", label="Setting"),
            TableColumn(key="value", label="Value"),
            TableColumn(key="version", label="Version", numeric=True),
        ],
        rows=[
            {
                "key": s.key,
                "value": _json(s.value).replace("\n", " ")[:VALUE_PREVIEW_MAX],
                "version": s.version,
            }
            for s in out.settings
        ],
        total=len(out.settings),
    )


async def _preview(ctx: ToolContext, args: ProposeChangeIn) -> ConfirmPreview:
    try:
        key = lookup_key(args.key)
        proposed = validate_value(key, args.value)
        async with ctx.uow_factory() as uow:
            entry = (await list_config_entries(uow, only=key.name))[0]
    except UnknownConfigKey as exc:
        raise ToolError("NOT_FOUND", f"There is no setting named {exc.key!r}.", 404) from exc
    except ConfigValidationError as exc:
        raise ToolError("INVALID_VALUE", f"That value is not valid: {exc}", 422) from exc
    before = _json(entry.value)
    after = _json(key.dump(proposed))
    diff = [
        *(DiffLine(op="-", text=line) for line in before.splitlines()),
        *(DiffLine(op="+", text=line) for line in after.splitlines()),
    ]
    return ConfirmPreview(
        what=f"Change setting {key.name}",
        before=before,
        after=after,
        who=who_line(ctx.principal),
        expected_version=entry.version,
        details=[PreviewField(label="Setting", value=entry.description)],
        diff=diff,
    )


async def _propose(ctx: ToolContext, args: ProposeChangeIn) -> ProposeChangeOut:
    confirmation = ctx.confirmation
    if confirmation is None or confirmation.expected_version is None:
        raise ToolError("CONFLICT", "The change was not confirmed. Nothing changed.", 409)
    runtime = await ctx.services.get(RuntimeConfig)
    try:
        async with ctx.uow_factory() as uow:
            await ConfigWriter(ctx.clock).set(
                uow,
                args.key,
                args.value,
                ctx.principal,
                confirmation.reason,
                confirmation.expected_version,
            )
            entry = (await list_config_entries(uow, only=args.key))[0]
            await uow.commit()
    except ConfigConflict as exc:
        raise ToolError(
            "CONFLICT", "The setting changed since the preview. Nothing changed.", 409
        ) from exc
    except ConfigError as exc:
        raise ToolError("INVALID_VALUE", f"{exc} Nothing changed.", 422) from exc
    runtime.invalidate()
    return ProposeChangeOut(key=entry.key, version=entry.version, value=entry.value)


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="settings.read",
        group=ToolGroup.SETTINGS,
        description=(
            "Read runtime settings with their current value, default and version. Pass `key` for "
            "one setting or `group` for a family (for example matching, models, retries); pass "
            "neither to list them all."
        ),
        input_model=SettingsReadIn,
        output_model=SettingsReadOut,
        permission=Permission.CONFIG_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Read settings",
        handler=_read,
        card=_read_card,
        summarize_input=lambda a: f"key={a.key or '*'} group={a.group or '*'}",
        summarize_output=lambda o: f"{len(o.settings)} setting(s)",
    ),
    ToolSpec(
        name="settings.propose_change",
        group=ToolGroup.SETTINGS,
        description=(
            "Propose a change to one runtime setting. This does not change anything: the person "
            "sees the current and new value and must confirm with a reason. Read the setting "
            "first so the new value has the right shape."
        ),
        input_model=ProposeChangeIn,
        output_model=ProposeChangeOut,
        permission=Permission.CONFIG_WRITE,
        mutating=True,
        confirm_required=True,
        audit_label="Changed a setting",
        handler=_propose,
        preview=_preview,
        summarize_input=lambda a: f"key={a.key}",
        summarize_output=lambda o: f"{o.key} is now at version {o.version}",
    ),
]
