"""The replay LLM client: recorded or scripted answers, no network.

Lives in ``src`` (not under ``tests``) so the evaluation harness can run a replay mode too.
The recordings under ``api/tests/fixtures/llm`` are synthetic and marked
``verified_against_live: false`` until a live probe has produced them.
"""

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ValidationError

from cashapp.integrations.llm.base import (
    LlmError,
    LlmErrorCode,
    LlmRequest,
    LlmResult,
    LlmUsage,
    ToolTurnComplete,
    ToolTurnDelta,
    ToolTurnEvent,
    ToolTurnRequest,
    parts_digest,
)

PROVIDER = "replay"

type Script = Sequence[ScriptedStep] | Mapping[str, Sequence[ScriptedStep]]


@dataclass(frozen=True, slots=True)
class ScriptedStep:
    result: LlmResult[Any] | None = None  # output may be a BaseModel or a dict
    error: LlmError | None = None
    delay_s: float = 0.0  # above request.timeout_s this simulates a timeout
    text_chunks: tuple[str, ...] = ()  # for stream_text and stream_tool_turn
    tool_blocks: tuple[dict[str, Any], ...] = ()  # extra content blocks (tool_use) for a tool turn
    stop_reason: str = "end_turn"  # for a tool turn; "tool_use" when tool_blocks hold calls


@dataclass(frozen=True, slots=True)
class Recording:
    purpose: str
    parts_sha256: str
    schema: str  # "RemittanceExtraction@1"
    result: dict[str, Any]
    verified_against_live: bool = False

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "Recording":
        return cls(
            purpose=str(raw["purpose"]),
            parts_sha256=str(raw["parts_sha256"]),
            schema=str(raw.get("schema", "")),
            result=dict(raw["result"]),
            verified_against_live=bool(raw.get("verified_against_live", False)),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "parts_sha256": self.parts_sha256,
            "schema": self.schema,
            "result": self.result,
            "verified_against_live": self.verified_against_live,
        }


def _usage_from(raw: Mapping[str, Any] | None, model_id: str) -> LlmUsage:
    raw = raw or {}
    return LlmUsage(
        model_id=str(raw.get("model_id", model_id)),
        input_tokens=int(raw.get("input_tokens", 0)),
        output_tokens=int(raw.get("output_tokens", 0)),
        latency_ms=int(raw.get("latency_ms", 0)),
    )


class ReplayLlmClient:
    provider = PROVIDER

    def __init__(
        self,
        *,
        model_id: str = "replay",
        recordings_dir: Path | None = None,
        script: Script | None = None,
    ) -> None:
        self._model_id = model_id
        self._recordings_dir = recordings_dir
        self._script = script
        # Shared with every client made by with_model(), so a rebound client keeps the cursor.
        self._cursor: dict[str, int] = {}
        self._recordings: dict[tuple[str, str], Recording] | None = None
        self.calls: list[LlmRequest] = []
        self.tool_calls: list[ToolTurnRequest] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def with_model(self, model_id: str) -> Self:
        clone = copy.copy(self)
        clone._model_id = model_id
        return clone

    @staticmethod
    def refusal(model_id: str = "replay") -> ScriptedStep:
        usage = LlmUsage(model_id=model_id, input_tokens=0, output_tokens=0, latency_ms=0)
        return ScriptedStep(
            result=LlmResult(output=None, refused=True, stop_reason="refusal", usage=usage)
        )

    @staticmethod
    def transient(model_id: str = "replay") -> ScriptedStep:
        return ScriptedStep(
            error=LlmError(
                LlmErrorCode.LLM_TRANSIENT,
                "simulated transient failure",
                provider=PROVIDER,
                model_id=model_id,
            )
        )

    @staticmethod
    def timeout(seconds: float = 3600.0) -> ScriptedStep:
        return ScriptedStep(delay_s=seconds)

    async def stream_tool_turn(self, request: ToolTurnRequest) -> AsyncIterator[ToolTurnEvent]:
        """A scripted tool turn: text deltas, then the text and tool blocks as final content."""
        self.tool_calls.append(request)
        script = self._script
        purpose_key = request.purpose
        steps = script.get(purpose_key) if isinstance(script, Mapping) else script
        if steps is None:
            raise self._fail(f"no script for purpose {purpose_key}")
        key = purpose_key if isinstance(script, Mapping) else ""
        index = self._cursor.get(key, 0)
        if index >= len(steps):
            raise self._fail("script exhausted")
        self._cursor[key] = index + 1
        step = steps[index]
        if step.delay_s:
            await asyncio.sleep(step.delay_s)
        if step.error is not None:
            raise step.error
        if step.result is not None and step.result.refused:
            raise self._fail("model refused", LlmErrorCode.LLM_REFUSAL)
        for chunk in step.text_chunks:
            yield ToolTurnDelta(chunk)
        text = "".join(step.text_chunks)
        blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
        blocks.extend(step.tool_blocks)
        usage = LlmUsage(model_id=self._model_id, input_tokens=0, output_tokens=0, latency_ms=0)
        yield ToolTurnComplete(content=tuple(blocks), stop_reason=step.stop_reason, usage=usage)

    def _fail(self, detail: str, code: LlmErrorCode = LlmErrorCode.EXTRACTION_FAILED) -> LlmError:
        return LlmError(code, detail, provider=PROVIDER, model_id=self._model_id)

    def _next_step(self, request: LlmRequest) -> ScriptedStep | None:
        script = self._script
        if script is None:
            return None
        if isinstance(script, Mapping):
            steps = script.get(request.purpose)
            if steps is None:
                raise self._fail(f"no script for purpose {request.purpose}")
            key = request.purpose
        else:
            steps = script
            key = ""
        index = self._cursor.get(key, 0)
        if index >= len(steps):
            raise self._fail("script exhausted")
        self._cursor[key] = index + 1
        return steps[index]

    def _load_recordings(self) -> dict[tuple[str, str], Recording]:
        if self._recordings is None:
            found: dict[tuple[str, str], Recording] = {}
            if self._recordings_dir is not None:
                for path in sorted(self._recordings_dir.glob("*.json")):
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and "parts_sha256" in raw:
                        record = Recording.from_json(raw)  # pyright: ignore[reportUnknownArgumentType]
                        found[(record.purpose, record.parts_sha256)] = record
            self._recordings = found
        return self._recordings

    def _from_recording(self, request: LlmRequest) -> ScriptedStep:
        record = self._load_recordings().get((request.purpose, parts_digest(request.parts)))
        if record is None:
            raise self._fail("no recording")
        raw = record.result
        output = raw.get("output")
        result: LlmResult[Any] = LlmResult(
            output=output,
            refused=bool(raw.get("refused", False)),
            stop_reason=str(raw.get("stop_reason", "end_turn")),
            usage=_usage_from(raw.get("usage"), self._model_id),
            response_id=raw.get("response_id"),
        )
        return ScriptedStep(result=result)

    async def parse[T: BaseModel](self, request: LlmRequest, schema: type[T]) -> LlmResult[T]:
        self.calls.append(request)
        step = self._next_step(request) or self._from_recording(request)
        if step.delay_s:
            await asyncio.sleep(step.delay_s)
        if step.error is not None:
            raise step.error
        if step.result is None:
            raise self._fail("scripted step has no result")
        scripted = step.result
        if scripted.refused or scripted.output is None:
            return LlmResult(
                output=None,
                refused=True,
                stop_reason=scripted.stop_reason,
                usage=scripted.usage,
                response_id=scripted.response_id,
            )
        raw = scripted.output
        try:
            if isinstance(raw, schema):
                output = raw
            elif isinstance(raw, BaseModel):
                output = schema.model_validate(raw.model_dump(mode="json"))
            else:
                output = schema.model_validate(raw)
        except ValidationError as exc:
            raise self._fail("scripted output does not match the schema") from exc
        return LlmResult(
            output=output,
            refused=False,
            stop_reason=scripted.stop_reason,
            usage=scripted.usage,
            response_id=scripted.response_id,
        )

    async def stream_text(self, request: LlmRequest) -> AsyncIterator[str]:
        self.calls.append(request)
        step = self._next_step(request)
        if step is None:
            raise self._fail("no script for streaming")
        if step.delay_s:
            await asyncio.sleep(step.delay_s)
        if step.error is not None:
            raise step.error
        if step.result is not None and step.result.refused:
            raise self._fail("model refused", LlmErrorCode.LLM_REFUSAL)
        for chunk in step.text_chunks:
            yield chunk
