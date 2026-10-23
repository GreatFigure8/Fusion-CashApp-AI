"""HTTP transport for Fusion: auth, headers, bounded retry with backoff, paging, spans, logs.

Nothing here logs or traces a URL query, a body, or a credential. Only method, pod, HTTP status,
attempt, latency and a Fusion code reach logs and spans.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError, error_from_http
from cashapp.observability.logging import get_logger
from cashapp.observability.tracing import span
from cashapp.settings import FusionPodSettings

_log = get_logger(__name__)

RFV_HEADER = {"REST-Framework-Version": "4"}

SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class FusionClientOptions:
    timeout_s: float = 60.0
    page_size: int = 500
    chunk_size: int = 50
    max_pages: int = 200
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0


# Failures where Fusion certainly did not process the request: safe to retry a write.
_NOT_PROCESSED = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_WRITE_RETRY_STATUS = frozenset({401, 503})


def loads_decimal(content: bytes) -> Any:
    """Parse JSON with every non-integer number as `Decimal`; money never passes through float."""
    return json.loads(content, parse_float=Decimal)


class FusionTransport:
    def __init__(
        self,
        *,
        pod_name: str,
        pod: FusionPodSettings,
        options: FusionClientOptions,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.pod_name = pod_name
        self.options = options
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=pod.base_url,
            auth=httpx.BasicAuth(pod.username, pod.password.get_secret_value()),
            timeout=options.timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- core ------------------------------------------------------------------------------

    def _delay(self, attempt: int) -> float:
        cap = min(self.options.backoff_max_s, self.options.backoff_base_s * (2 ** (attempt - 1)))
        return random.uniform(0, cap)  # noqa: S311 - jitter, not security

    async def request(
        self,
        method: str,
        url: str,
        *,
        op: str,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        write: bool = False,
        soap_fault_ok: bool = False,
    ) -> httpx.Response:
        """Send with bounded retry. Returns the response for 2xx (and SOAP-fault 500s if allowed).

        Reads retry every transient failure. Writes retry only when Fusion certainly did not
        process the request; any other transient write failure raises `outcome_unknown=True`.
        """
        started = time.perf_counter()
        last_error: FusionError | None = None
        attempts = 0
        with span(f"fusion.{op}", pod=self.pod_name) as active:
            for attempt in range(1, self.options.max_attempts + 1):
                attempts = attempt
                try:
                    response = await self._client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        content=content,
                        headers=headers,
                    )
                except httpx.TimeoutException as exc:
                    certain = isinstance(exc, _NOT_PROCESSED)
                    last_error = FusionError(
                        ErrorCode.FUSION_TRANSIENT,
                        f"{type(exc).__name__} calling Fusion",
                        outcome_unknown=write and not certain,
                    )
                    retry = certain or not write
                except httpx.TransportError as exc:
                    certain = isinstance(exc, _NOT_PROCESSED)
                    last_error = FusionError(
                        ErrorCode.FUSION_TRANSIENT,
                        f"{type(exc).__name__} calling Fusion",
                        outcome_unknown=write and not certain,
                    )
                    retry = certain or not write
                else:
                    if response.is_success or (
                        soap_fault_ok
                        and response.status_code == 500
                        and b"Fault" in response.content
                    ):
                        self._finish(op, response.status_code, attempts, started, None)
                        active.set(status=response.status_code, attempts=attempts)
                        return response
                    error = error_from_http(response.status_code, response.content)
                    if not error.retryable:
                        self._finish(op, response.status_code, attempts, started, error)
                        active.set(status=response.status_code, attempts=attempts)
                        raise error
                    if write:
                        retry = response.status_code in _WRITE_RETRY_STATUS
                        error.outcome_unknown = not retry
                    else:
                        retry = True
                    last_error = error
                if not retry or attempt >= self.options.max_attempts:
                    break
                await self._sleep(self._delay(attempt))
            assert last_error is not None  # noqa: S101 - loop always sets it before breaking
            self._finish(op, last_error.http_status, attempts, started, last_error)
            active.set(status=last_error.http_status or 0, attempts=attempts)
            raise last_error

    def _finish(
        self,
        op: str,
        status: int | None,
        attempts: int,
        started: float,
        error: FusionError | None,
    ) -> None:
        _log.info(
            "fusion call",
            extra={
                "fusion_method": op,
                "pod": self.pod_name,
                "http_status": status,
                "attempts": attempts,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "fusion_code": error.code.value if error else None,
            },
        )

    # --- REST ------------------------------------------------------------------------------

    @staticmethod
    def _rest_params(params: Mapping[str, str] | None, fields: str | None) -> dict[str, str]:
        merged = dict(params or {})
        merged["onlyData"] = "true"
        if fields is not None:
            merged["fields"] = fields
        return merged

    async def get_json(
        self, url: str, *, op: str, params: Mapping[str, str] | None = None, fields: str | None
    ) -> dict[str, Any]:
        response = await self.request(
            "GET",
            url,
            op=op,
            params=self._rest_params(params, fields),
            headers={**RFV_HEADER, "Accept": "application/json"},
        )
        return _as_object(loads_decimal(response.content))

    async def get_json_paged(
        self,
        url: str,
        *,
        op: str,
        fields: str,
        params: Mapping[str, str] | None = None,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """Follow `hasMore`/`offset`. Stops on an empty page even if `hasMore` lies."""
        if not fields:
            raise ValueError("fields= is required on every REST read")
        items: list[dict[str, Any]] = []
        offset = 0
        for _ in range(self.options.max_pages):
            page_params = {**(params or {}), "limit": str(self.options.page_size)}
            page_params["offset"] = str(offset)
            body = await self.get_json(url, op=op, params=page_params, fields=fields)
            page = body.get("items", [])
            rows = [_as_object(row) for row in page] if isinstance(page, list) else []  # pyright: ignore[reportUnknownVariableType]
            items.extend(rows)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            if not rows or body.get("hasMore") is not True:
                return items
            offset += len(rows)
        raise FusionError(ErrorCode.FUSION_FAULT, f"{op}: exceeded {self.options.max_pages} pages")

    async def send_json(
        self, method: str, url: str, body: Mapping[str, Any], *, op: str
    ) -> dict[str, Any]:
        """Guarded-write JSON call (POST/PATCH); the caller has already run the write guard."""
        response = await self.request(
            method,
            url,
            op=op,
            json_body=body,
            headers={**RFV_HEADER, "Accept": "application/json"},
            write=True,
        )
        if not response.content:
            return {}
        return _as_object(loads_decimal(response.content))

    # --- SOAP ------------------------------------------------------------------------------

    async def post_soap(
        self, url: str, envelope: bytes, *, action: str, op: str, write: bool
    ) -> bytes:
        response = await self.request(
            "POST",
            url,
            op=op,
            content=envelope,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": action,
                "Accept": "text/xml",
            },
            write=write,
            soap_fault_ok=True,
        )
        return response.content


def _as_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FusionError(ErrorCode.FUSION_FAULT, "Fusion returned an unexpected JSON shape")
    return value  # pyright: ignore[reportUnknownVariableType]
