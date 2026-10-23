"""Errors the chat service raises before a stream starts (the router maps them to JSON)."""


class ChatError(Exception):
    """Base for pre-stream chat failures."""


class ChatNotFound(ChatError):  # noqa: N818 - pinned name
    """The item the chat is about does not exist."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"work item {item_id} not found")
        self.item_id = item_id


class ChatInvalid(ChatError):  # noqa: N818 - pinned name
    """The request is well-formed JSON but not a valid chat turn."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ThreadNotFound(ChatError):  # noqa: N818 - pinned name
    """The thread does not exist or belongs to someone else (the router answers 404 for both)."""

    def __init__(self, thread_id: int) -> None:
        super().__init__(f"thread {thread_id} not found")
        self.thread_id = thread_id


class ToolCallNotFound(ChatError):  # noqa: N818 - pinned name
    """No pending tool call has that id."""

    def __init__(self, call_id: str) -> None:
        super().__init__("tool call not found")
        self.call_id = call_id


class ToolCallConflict(ChatError):  # noqa: N818 - pinned name
    """The call cannot be decided.

    The code is ``tool_call_expired``, ``tool_call_not_yours`` or ``tool_call_decided``.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ChatForbidden(ChatError):  # noqa: N818 - pinned name
    """The caller lost the permission the proposed tool needs."""

    def __init__(self, permission: str) -> None:
        super().__init__(f"missing permission {permission}")
        self.permission = permission
