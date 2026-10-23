"""Request-id context shared by the middleware, the error handlers and logging."""

from contextvars import ContextVar
from typing import Final

REQUEST_ID_HEADER: Final = "X-Request-ID"

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the id of the request being handled, if any."""
    return request_id_var.get()
