"""The single error shape for every non-2xx response, defined once."""

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from cashapp.api.request_context import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)

_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[dict[str, Any]] = []


class ErrorEnvelope(BaseModel):
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorEnvelope},
    "5XX": {"model": ErrorEnvelope},
}


class ApiError(Exception):
    """Raise from anywhere below a router to produce the single error shape."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
        *,
        details: Sequence[Mapping[str, Any]] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message if message is not None else code.replace("_", " ").capitalize()
        self.details: list[dict[str, Any]] = [dict(d) for d in details]
        self.headers: dict[str, str] | None = dict(headers) if headers is not None else None
        super().__init__(self.message)


def _request_id(request: Request) -> str:
    state_id = request.scope.get("state", {}).get("request_id")
    if isinstance(state_id, str):
        return state_id
    return get_request_id() or uuid.uuid4().hex


def _response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = ErrorEnvelope(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=details or [])
    )
    merged = dict(headers or {})
    merged[REQUEST_ID_HEADER] = request_id
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=merged)


async def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    return _response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details: list[dict[str, Any]] = [
        {"loc": list(err["loc"]), "msg": str(err["msg"]), "type": str(err["type"])}
        for err in exc.errors()
    ]
    return _response(request, 422, "validation_error", "Request validation failed.", details)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = str(exc.detail) if exc.detail else code.replace("_", " ").capitalize()
    return _response(request, exc.status_code, code, message, headers=exc.headers)


async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", exc_info=exc)
    return _response(request, 500, "internal_error", "An unexpected error occurred.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unhandled)
