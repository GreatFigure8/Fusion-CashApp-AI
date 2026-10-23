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
