"""Errors the pipeline runtime raises or accepts from stations."""

from collections.abc import Mapping
from typing import Any

from cashapp.domain.error_codes import ErrorCode


class StageError(Exception):
    """A classified failure raised by a station.

    ``detail`` must be JSON-serialisable and free of personal data (ids, codes, amounts): it is
    stored in ``WORK_ITEM.LAST_ERROR_DETAIL`` and shown in the UI.
    """

    def __init__(
        self,
        code: ErrorCode,
        detail: Mapping[str, Any] | None = None,
        message: str | None = None,
    ) -> None:
        self.code = code
        self.detail: dict[str, Any] = dict(detail) if detail is not None else {}
        self.message = message if message is not None else code.spec.description
        super().__init__(self.message)


class MalformedEvent(Exception):  # noqa: N818 - pinned name
    """The bytes on the bus are not a valid ``StageEvent``."""


class RunnerInfrastructureError(Exception):
    """The runner could not persist its own bookkeeping (database unreachable, for example).

    The offset is not committed; the consumer retries the same delivery.
    """
