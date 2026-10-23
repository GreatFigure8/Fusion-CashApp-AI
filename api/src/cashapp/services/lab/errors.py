"""Matching lab errors. Each carries the code the router maps into the single error shape."""

from collections.abc import Sequence
from typing import Any


class LabError(Exception):
    """Base class; ``code`` and ``status`` are what the transmission layer reports."""

    code = "LAB_ERROR"
    status = 400

    def __init__(self, message: str, *, details: Sequence[dict[str, Any]] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.details: list[dict[str, Any]] = list(details)


class LabKeyNotAllowed(LabError):  # noqa: N818
    code = "KEY_NOT_ALLOWED"
    status = 422


class LabOutOfBounds(LabError):  # noqa: N818
    code = "OUT_OF_BOUNDS"
    status = 422


class LabInvalidValue(LabError):  # noqa: N818
    code = "INVALID_VALUE"
    status = 422


class LabReasonRequired(LabError):  # noqa: N818
    code = "REASON_REQUIRED"
    status = 422


class LabWindowOutOfRange(LabError):  # noqa: N818
    code = "WINDOW_OUT_OF_RANGE"
    status = 422


class LabInvalidId(LabError):  # noqa: N818
    code = "INVALID_ID"
    status = 422


class LabNotFound(LabError):  # noqa: N818
    code = "NOT_FOUND"
    status = 404


class LabCandidateNotFound(LabNotFound):
    code = "CANDIDATE_NOT_FOUND"


class LabReplayNotFound(LabNotFound):
    code = "REPLAY_NOT_FOUND"


class LabForbidden(LabError):  # noqa: N818
    code = "forbidden"
    status = 403


class LabStale(LabError):  # noqa: N818
    code = "STALE"
    status = 409

    def __init__(self, live_version: int) -> None:
        super().__init__(f"Live config moved to v{live_version}")
        self.live_version = live_version


class LabReplayNotDone(LabError):  # noqa: N818
    code = "REPLAY_NOT_DONE"
    status = 409


class LabReplayRunning(LabError):  # noqa: N818
    code = "REPLAY_RUNNING"
    status = 409


class LabCandidateClosed(LabError):  # noqa: N818
    code = "CANDIDATE_CLOSED"
    status = 409
