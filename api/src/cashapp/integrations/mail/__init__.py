"""Mailbox sources. The real adapter is added after the s33 mailbox decision."""

from cashapp.integrations.mail.fake import FakeMailboxSource

__all__ = ["FakeMailboxSource"]
