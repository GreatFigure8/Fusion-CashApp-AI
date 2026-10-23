"""Cohere Command A Vision on OCI Generative AI, reached through a dedicated AI cluster.

On-demand serving of this model is retired in Ashburn, so every call uses
``DedicatedServingMode`` against the cluster endpoint from configuration. The OCI SDK is
synchronous: each call runs in a worker thread, and the SDK read timeout equals the role timeout
so an abandoned thread ends on its own. The request shape (Cohere V2 chat, JSON response format)
is marked unverified until the live probe has passed against the dedicated endpoint.
"""

import asyncio
import base64
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final, Protocol, Self

import oci as _oci  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, ValidationError

from cashapp.integrations.llm.base import (
    ImagePart,
    LlmError,
    LlmErrorCode,
    LlmRequest,
    LlmResult,
    LlmUsage,
    PdfPart,
    TextPart,
)
from cashapp.integrations.llm.pdf import pdf_to_text_and_images

# The OCI SDK ships no type information; everything reached through it is Any on purpose.
oci: Any = _oci

PROVIDER = "oci-cohere"
_CONNECT_TIMEOUT_S: Final = 10.0
_OCI_CONFIG_PATH: Final = Path.home() / ".oci" / "config"
_FILTER_MARKERS: Final = ("FILTER", "SAFETY", "BLOCK")


class CohereChatTransport(Protocol):
    """Seam over ``GenerativeAiInferenceClient.chat``: synchronous, returns the ``ChatResult``."""

    def chat(self, details: Any, *, timeout_s: float) -> Any: ...


def _signer_config() -> tuple[dict[str, Any], Any]:
    """Resource principal when deployed as a function, instance principal on compute, else a
    local ``~/.oci/config`` profile for development."""
    if os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
        return {}, oci.auth.signers.get_resource_principals_signer()
    try:
        return {}, oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    except Exception:
        # Not on OCI compute: fall back to the developer's config file.
        return oci.config.from_file(str(_OCI_CONFIG_PATH)), None


class OciGenAiTransport:
    """The real transport. One SDK client per distinct read timeout, created on first use."""

    def __init__(self, service_endpoint: str) -> None:
        self._endpoint = service_endpoint
        self._clients: dict[float, Any] = {}

    def _client(self, timeout_s: float) -> Any:
        existing = self._clients.get(timeout_s)
        if existing is not None:
            return existing
        config, signer = _signer_config()
        kwargs: dict[str, Any] = {
            "service_endpoint": self._endpoint,
            "timeout": (_CONNECT_TIMEOUT_S, timeout_s),
            "retry_strategy": oci.retry.NoneRetryStrategy(),
        }
        if signer is not None:
            kwargs["signer"] = signer
        client: Any = oci.generative_ai_inference.GenerativeAiInferenceClient(config, **kwargs)
        self._clients[timeout_s] = client
        return client

    def chat(self, details: Any, *, timeout_s: float) -> Any:
        return self._client(timeout_s).chat(details).data


def _data_url(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{base64.standard_b64encode(data).decode('ascii')}"


def _strip_fence(text: str) -> str:
    """Remove one leading and one trailing code fence, nothing else."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        stripped = stripped[first_newline + 1 :] if first_newline != -1 else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()


class OciCohereLlmClient:
    provider = PROVIDER

    def __init__(
        self,
        transport: CohereChatTransport,
        *,
        model_id: str,
        compartment_ocid: str,
        endpoint_ocid: str,
    ) -> None:
        self._transport = transport
        self._model_id = model_id
        self._compartment_ocid = compartment_ocid
        self._endpoint_ocid = endpoint_ocid

    @property
    def model_id(self) -> str:
        return self._model_id

    def with_model(self, model_id: str) -> Self:
        return type(self)(
            self._transport,
            model_id=model_id,
            compartment_ocid=self._compartment_ocid,
            endpoint_ocid=self._endpoint_ocid,
        )

    def _error(self, code: LlmErrorCode, detail: str, usage: LlmUsage | None = None) -> LlmError:
        return LlmError(code, detail, provider=PROVIDER, model_id=self._model_id, usage=usage)

    def _content(self, request: LlmRequest, schema: type[BaseModel]) -> list[Any]:
        models: Any = oci.generative_ai_inference.models
        content: list[Any] = []
        for part in request.parts:
            if isinstance(part, TextPart):
                content.append(models.CohereTextContentV2(text=part.text))
            elif isinstance(part, ImagePart):
                content.append(
                    models.CohereImageContentV2(
                        image_url=models.CohereImageUrlV2(url=_data_url(part.media_type, part.data))
                    )
                )
            elif isinstance(part, PdfPart):  # pyright: ignore[reportUnnecessaryIsInstance]
                try:
                    rendering = pdf_to_text_and_images(part.data)
                except ValueError as exc:
                    raise self._error(LlmErrorCode.EXTRACTION_FAILED, str(exc)) from exc
                if rendering.text:
                    content.append(models.CohereTextContentV2(text=rendering.text))
                for image in rendering.images:
                    content.append(
                        models.CohereImageContentV2(
                            image_url=models.CohereImageUrlV2(
                                url=_data_url(image.media_type, image.data)
                            )
                        )
                    )
        schema_json = json.dumps(schema.model_json_schema())
        content.append(
            models.CohereTextContentV2(
                text=(
                    "Reply with one JSON object only, no commentary and no code fence, that "
                    "validates against this JSON Schema:\n" + schema_json
                )
            )
        )
        return content

    def _details(self, request: LlmRequest, schema: type[BaseModel]) -> Any:
        models: Any = oci.generative_ai_inference.models
        chat_request = models.CohereChatRequestV2(
            messages=[
                models.CohereSystemMessageV2(
                    content=[models.CohereTextContentV2(text=request.system)]
                ),
                models.CohereUserMessageV2(content=self._content(request, schema)),
            ],
            response_format=models.CohereResponseJsonFormat(schema=schema.model_json_schema()),
            max_tokens=request.max_tokens,
            temperature=0.0,
            is_stream=False,
        )
        return models.ChatDetails(
            compartment_id=self._compartment_ocid,
            serving_mode=models.DedicatedServingMode(endpoint_id=self._endpoint_ocid),
            chat_request=chat_request,
        )

    def _map(self, exc: Exception) -> LlmError:
        if isinstance(exc, oci.exceptions.ServiceError):
            status = int(getattr(exc, "status", 0))
            if status in {408, 429} or status >= 500:
                return self._error(LlmErrorCode.LLM_TRANSIENT, f"service error {status}")
            return self._error(LlmErrorCode.EXTRACTION_FAILED, f"request rejected {status}")
        if isinstance(
            exc,
            (
                oci.exceptions.RequestException,
                oci.exceptions.ConnectTimeout,
                TimeoutError,
                ConnectionError,
            ),
        ):
            return self._error(LlmErrorCode.LLM_TRANSIENT, "connection failed or timed out")
        return self._error(LlmErrorCode.EXTRACTION_FAILED, f"unexpected {type(exc).__name__}")

    @staticmethod
    def _reply_text(chat_response: Any) -> str:
        message = getattr(chat_response, "message", None)
        pieces: list[str] = []
        items: list[Any] = list(getattr(message, "content", None) or [])
        for item in items:
            piece: Any = getattr(item, "text", None)
            if isinstance(piece, str):
                pieces.append(piece)
        return "".join(pieces)

    async def parse[T: BaseModel](self, request: LlmRequest, schema: type[T]) -> LlmResult[T]:
        started = time.perf_counter()
        try:
            details = self._details(request, schema)
            result: Any = await asyncio.to_thread(
                self._transport.chat, details, timeout_s=request.timeout_s
            )
        except LlmError:
            raise
        except Exception as exc:
            raise self._map(exc) from exc
        chat_response: Any = result.chat_response
        raw_usage = getattr(chat_response, "usage", None)
        usage = LlmUsage(
            model_id=self._model_id,
            input_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        finish = str(getattr(chat_response, "finish_reason", "") or "")
        response_id = getattr(chat_response, "id", None)
        if any(marker in finish.upper() for marker in _FILTER_MARKERS):
            return LlmResult(
                output=None, refused=True, stop_reason=finish, usage=usage, response_id=response_id
            )
        if finish.upper() in {"MAX_TOKENS", "ERROR"}:
            raise self._error(LlmErrorCode.EXTRACTION_FAILED, f"finish {finish}", usage)
        try:
            output = schema.model_validate_json(_strip_fence(self._reply_text(chat_response)))
        except (ValidationError, ValueError) as exc:
            raise self._error(
                LlmErrorCode.EXTRACTION_FAILED, "output failed schema validation", usage
            ) from exc
        return LlmResult(
            output=output, refused=False, stop_reason=finish, usage=usage, response_id=response_id
        )

    async def stream_text(self, request: LlmRequest) -> AsyncIterator[str]:
        raise NotImplementedError("Cohere is reader-only")
        yield ""  # pragma: no cover - makes this an async generator to match the protocol
