"""Claude through the Anthropic SDK: structured outputs for parsing, streaming for chat.

Rules for the current Opus models, each of which is a 400 if broken: thinking is never sent as
disabled and has no budget, effort is always set explicitly by the caller, no ``tool_choice``,
no sampling parameters, no assistant prefill. A refusal stop reason is checked before the
content is read. SDK retries are off: every retry belongs to the auto-fix engine so each
attempt is recorded. Model ids containing "fable" are refused (zero data retention).
"""

import base64
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, Self

import anthropic
from pydantic import BaseModel, SecretStr, ValidationError

from cashapp.integrations.llm.base import (
    ContentPart,
    ImagePart,
    LlmError,
    LlmErrorCode,
    LlmRequest,
    LlmResult,
    LlmUsage,
    PdfPart,
    TextPart,
)

PROVIDER = "anthropic"


def _ignore_usage(usage: LlmUsage) -> None:
    """The no-op callback ``stream_text`` passes when nobody meters the stream."""


def refuse_fable(model_id: str) -> None:
    if "fable" in model_id.lower():
        raise ValueError("Fable models are not allowed: zero data retention is required")


def _blocks(parts: Sequence[ContentPart]) -> list[dict[str, Any]]:
    """Content blocks in part order. Documents and images keep their place before the text."""
    blocks: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, PdfPart):
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(part.data).decode("ascii"),
                    },
                }
            )
        elif isinstance(part, ImagePart):  # pyright: ignore[reportUnnecessaryIsInstance]
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": base64.standard_b64encode(part.data).decode("ascii"),
                    },
                }
            )
    return blocks


def _messages(request: LlmRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": turn.role, "content": turn.text} for turn in request.history
    ]
    messages.append({"role": "user", "content": _blocks(request.parts)})
    return messages


class AnthropicClientProvider:
    """One shared SDK client, rebuilt when the resolved API key changes (rotation).

    The key is resolved at call time through the secret resolver's TTL cache, so a rotated Vault
    secret is picked up without a restart. SDK retries are off: the auto-fix engine owns retries.
    """

    def __init__(
        self, api_key: Callable[[], Awaitable[SecretStr]], *, base_url: str | None = None
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client: anthropic.AsyncAnthropic | None = None
        self._key: str | None = None

    async def get(self) -> anthropic.AsyncAnthropic:
        key = (await self._api_key()).get_secret_value()
        if self._client is None or key != self._key:
            self._client = anthropic.AsyncAnthropic(
                api_key=key, base_url=self._base_url, max_retries=0
            )
            self._key = key
        return self._client


class AnthropicLlmClient:
    provider = PROVIDER

    def __init__(self, client: AnthropicClientProvider, model_id: str) -> None:
        refuse_fable(model_id)
        self._client = client
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def with_model(self, model_id: str) -> Self:
        return type(self)(self._client, model_id)

    def _error(self, code: LlmErrorCode, detail: str, usage: LlmUsage | None = None) -> LlmError:
        return LlmError(code, detail, provider=PROVIDER, model_id=self._model_id, usage=usage)

    def _map(self, exc: Exception) -> LlmError:
        """Typed SDK exceptions, most specific first. No message text is copied."""
        if isinstance(exc, anthropic.RateLimitError):
            return self._error(LlmErrorCode.LLM_TRANSIENT, "rate limited")
        if isinstance(exc, anthropic.APITimeoutError):
            return self._error(LlmErrorCode.LLM_TRANSIENT, "request timed out")
        if isinstance(exc, anthropic.APIConnectionError):
            return self._error(LlmErrorCode.LLM_TRANSIENT, "connection failed")
        if isinstance(exc, anthropic.InternalServerError):
            return self._error(LlmErrorCode.LLM_TRANSIENT, f"server error {exc.status_code}")
        if isinstance(exc, anthropic.APIStatusError):
            if exc.status_code >= 500 or exc.status_code in {408, 409, 429}:
                return self._error(LlmErrorCode.LLM_TRANSIENT, f"status {exc.status_code}")
            return self._error(
                LlmErrorCode.EXTRACTION_FAILED, f"request rejected {exc.status_code}"
            )
        if isinstance(exc, ValidationError):
            return self._error(LlmErrorCode.EXTRACTION_FAILED, "output failed schema validation")
        return self._error(LlmErrorCode.EXTRACTION_FAILED, f"unexpected {type(exc).__name__}")

    def _usage(self, response: Any, started: float) -> LlmUsage:
        usage = getattr(response, "usage", None)
        return LlmUsage(
            model_id=self._model_id,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _call_kwargs(self, request: LlmRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model_id,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": _messages(request),
        }
        if request.effort is not None:
            kwargs["output_config"] = {"effort": request.effort}
        return kwargs

    async def parse[T: BaseModel](self, request: LlmRequest, schema: type[T]) -> LlmResult[T]:
        started = time.perf_counter()
        client = (await self._client.get()).with_options(timeout=request.timeout_s)
        try:
            response: Any = await client.messages.parse(
                output_format=schema, **self._call_kwargs(request)
            )
        except Exception as exc:
            raise self._map(exc) from exc
        usage = self._usage(response, started)
        stop_reason = str(response.stop_reason)
        # Refusal first: a refused response has no content to read.
        if stop_reason == "refusal":
            return LlmResult(
                output=None,
                refused=True,
                stop_reason=stop_reason,
                usage=usage,
                response_id=getattr(response, "id", None),
            )
        if stop_reason == "max_tokens":
            raise self._error(LlmErrorCode.EXTRACTION_FAILED, "max_tokens", usage)
        try:
            parsed: Any = response.parsed_output
        except Exception as exc:
            raise self._error(
                LlmErrorCode.EXTRACTION_FAILED, "output could not be parsed", usage
            ) from exc
        if parsed is None:
            raise self._error(LlmErrorCode.EXTRACTION_FAILED, "no structured output", usage)
        return LlmResult(
            output=parsed,
            refused=False,
            stop_reason=stop_reason,
            usage=usage,
            response_id=getattr(response, "id", None),
        )

    def stream_text(self, request: LlmRequest) -> AsyncIterator[str]:
        return self.stream_text_metered(request, _ignore_usage)

    async def stream_text_metered(
        self, request: LlmRequest, on_usage: Callable[[LlmUsage], None]
    ) -> AsyncIterator[str]:
        """Text deltas of a plain-text reply; the final usage goes to ``on_usage``."""
        started = time.perf_counter()
        client = (await self._client.get()).with_options(timeout=request.timeout_s)
        try:
            async with client.messages.stream(**self._call_kwargs(request)) as stream:
                async for delta in stream.text_stream:
                    yield delta
                final: Any = await stream.get_final_message()
        except Exception as exc:
            raise self._map(exc) from exc
        on_usage(self._usage(final, started))
        if str(final.stop_reason) == "refusal":
            raise self._error(LlmErrorCode.LLM_REFUSAL, "model refused")
