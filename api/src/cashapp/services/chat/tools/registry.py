"""The one tool registry: every chat tool's schema, permission, flags, handler and preview.

A tool module under ``cashapp/services/chat/tools/`` exports ``TOOLS: list[ToolSpec]``; nothing
else registers a tool and nothing runs a handler except ``ToolRunner``. The model sees a tool only
through ``anthropic_tools`` for the caller's principal, so a tool the person may not use is never
offered.
"""

import inspect
import re
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.principal import Permission, Principal
from cashapp.services.chat.tools.cards import ResultCard

__all__ = [
    "ConfirmPreview",
    "Confirmation",
    "DiffLine",
    "PreviewField",
    "Provider",
    "ToolContext",
    "ToolError",
    "ToolGroup",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolServices",
    "ToolSpec",
    "UnknownTool",
    "who_line",
]

NAME_PATTERN: Final = re.compile(r"^[a-z]+(\.[a-z_]+)+$")


class ToolGroup(StrEnum):
    ENGINE = "engine"
    LAB = "lab"
    SETTINGS = "settings"
    REPORTS = "reports"
    REVIEW = "review"
    EXCEPTIONS = "exceptions"
    FUSION_READS = "fusion_reads"
    METRICS = "metrics"


class PreviewField(BaseModel):
    label: str
    value: str


class DiffLine(BaseModel):
    op: Literal["-", "+", " "]
    text: str


class ConfirmPreview(BaseModel):
    what: str  # "Pause station apply"
    before: str
    after: str
    who: str  # who_line(principal)
    reason_prompt: str = "Why are you making this change?"
    expected_version: int | None = None
    details: list[PreviewField] = []
    diff: list[DiffLine] = []


@dataclass(frozen=True, slots=True)
class Confirmation:
    call_id: str
    reason: str
    expected_version: int | None  # the confirm body's value, else the preview's


Provider = Callable[[], object | Awaitable[object]]


class ToolError(Exception):
    """An expected tool failure. The message is safe to show the person and the model."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class ToolRegistrationError(Exception):
    """A spec or registration that breaks the registry's rules (raised at startup)."""


class UnknownTool(KeyError):  # noqa: N818 - pinned name
    """No registered tool has that name."""


class ToolServices:
    """Services a tool handler may fetch, built lazily by API-layer provider modules."""

    def __init__(self, providers: Mapping[type[Any], Provider]) -> None:
        self._providers = dict(providers)
        self._built: dict[type[Any], object] = {}

    async def get[T](self, kind: type[T]) -> T:
        built: object | None = self._built.get(kind)
        if built is None:
            provider = self._providers.get(kind)
            if provider is None:
                raise ToolError("SERVICE_UNAVAILABLE", "That service is not available.", 503)
            made = provider()
            built = await made if inspect.isawaitable(made) else made
            self._built[kind] = built
        if not isinstance(built, kind):
            raise ToolError("SERVICE_UNAVAILABLE", "That service is not available.", 503)
        return built


@dataclass(frozen=True, slots=True)
class ToolContext:
    principal: Principal
    uow_factory: UowFactory
    clock: Clock
    services: ToolServices
    thread_id: int
    call_id: str
    confirmation: Confirmation | None  # None for read tools and for previews
    progress: Callable[[int, int], Awaitable[None]]  # emits tool_progress{call_id, done, total}


@dataclass(frozen=True, slots=True)
class ToolSpec[InT: BaseModel, OutT: BaseModel]:
    name: str  # ^[a-z]+(\.[a-z_]+)+$ , e.g. "engine.pause"
    group: ToolGroup
    description: str  # prompt surface: the model reads it
    input_model: type[InT]  # never carries `reason`: the person types it at confirm
    output_model: type[OutT]  # dumped (JSON) back to the model as data
    permission: Permission
    mutating: bool
    confirm_required: bool  # True whenever mutating
    audit_label: str  # "Paused a station"
    handler: Callable[[ToolContext, InT], Awaitable[OutT]]
    preview: Callable[[ToolContext, InT], Awaitable[ConfirmPreview]] | None = None
    card: Callable[[OutT], ResultCard | None] | None = None
    summarize_input: Callable[[InT], str] | None = None  # audit + tool_started, 200 chars at most
    summarize_output: Callable[[OutT], str] | None = None  # tool_finished summary
    timeout_s: float = 30.0

    def __post_init__(self) -> None:
        if not NAME_PATTERN.match(self.name):
            raise ToolRegistrationError(f"tool name {self.name!r} must look like 'group.action'")
        if self.mutating and not self.confirm_required:
            raise ToolRegistrationError(f"mutating tool {self.name} must require confirmation")
        if self.confirm_required and self.preview is None:
            raise ToolRegistrationError(f"confirm-required tool {self.name} needs a preview")

    @property
    def wire_name(self) -> str:
        """Anthropic tool names forbid dots."""
        return self.name.replace(".", "__")


class ToolRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, ToolSpec[Any, Any]] = {}
        self._by_wire: dict[str, ToolSpec[Any, Any]] = {}

    def register(self, spec: ToolSpec[Any, Any]) -> None:
        if spec.name in self._by_name:
            raise ToolRegistrationError(f"tool {spec.name} is registered twice")
        self._by_name[spec.name] = spec
        self._by_wire[spec.wire_name] = spec

    def get(self, name: str) -> ToolSpec[Any, Any]:
        spec = self._by_name.get(name)
        if spec is None:
            raise UnknownTool(name)
        return spec

    def get_by_wire_name(self, wire: str) -> ToolSpec[Any, Any]:
        spec = self._by_wire.get(wire)
        if spec is None:
            raise UnknownTool(wire)
        return spec

    def all(self) -> list[ToolSpec[Any, Any]]:
        return [self._by_name[name] for name in sorted(self._by_name)]

    def for_principal(
        self, principal: Principal, groups: Collection[ToolGroup] | None = None
    ) -> list[ToolSpec[Any, Any]]:
        """Tools the principal may use. ``groups`` only narrows the set, it never widens it."""
        return [
            spec
            for spec in self.all()
            if principal.can(spec.permission) and (groups is None or spec.group in groups)
        ]

    def anthropic_tools(
        self, principal: Principal, groups: Collection[ToolGroup] | None = None
    ) -> list[dict[str, Any]]:
        """The tool definitions for the model, in a stable order (the cache needs it)."""
        return [
            {
                "name": spec.wire_name,
                "description": spec.description,
                "input_schema": spec.input_model.model_json_schema(),
                "eager_input_streaming": True,
            }
            for spec in self.for_principal(principal, groups)
        ]


def who_line(principal: Principal) -> str:
    """ "J. Stevenson · admin": who is making the change, for the confirm card."""
    roles = ", ".join(sorted(role.value.lower() for role in principal.roles))
    return f"{principal.display_name} · {roles}" if roles else principal.display_name
