# Spike: mailbox access method for the intake poller

Issue #33. Decision only. No adapter code, no configuration keys, no contact with any real mailbox.

## Open questions for Jonathan

1. **Platform.** Is the client's mail platform Microsoft 365 / Exchange Online, Google Workspace, or on-prem Exchange / other IMAP?
2. **Mailbox names.** Which remittance mailbox address(es) does intake read, and which source folder (default `Inbox`)? Which backlog folder(s) should be reprocessed?
3. **Tenant admin consent.** Who grants tenant admin consent (Graph), or provisions the service account / OAuth client (IMAP)? For Graph, who can apply the Exchange application access policy?
4. **Folders.** May `CashApp/Processed` and `CashApp/Failed` be created in the shared mailbox?

## Status

Decision: provisional. Unverified against a live mailbox. Built against `FakeMailboxSource`. The comparison is written from vendor knowledge, not fetched live; Graph throttling numbers and IMAP MOVE support are marked "verify on first live probe".

## Comparison

| Dimension | Microsoft Graph | IMAP |
|---|---|---|
| Protocol | HTTPS REST, `graph.microsoft.com/v1.0` | IMAP4rev1 over TLS 993 (`aioimaplib`, or `imaplib` in `asyncio.to_thread`) |
| Auth | App registration with application permission `Mail.ReadWrite`, restricted by an Exchange application access policy (RBAC for Applications) to a mail-enabled security group containing only the remittance mailbox(es). Client-credentials flow with a certificate (preferred) or client secret. Until the policy is applied the grant is tenant-wide, so apply it before any credential is stored. | Service account using OAuth2 SASL `XOAUTH2` (Microsoft 365 and Google have turned off basic auth), or an app password where the platform still allows it |
| Folders | `mailFolders/{id}/messages/delta` delta queries on the source folder, with the `deltaLink` kept in the database; `POST /messages/{id}/move` to the destination folder | `UID SEARCH` on the source folder; `UID MOVE` (RFC 6851; fallback `COPY` + `\Deleted` + `UID EXPUNGE`) to `CashApp/Processed`; `UIDVALIDITY` stored with the last UID (verify MOVE support on first live probe) |
| Processed-mail convention | Move to `CashApp/Processed` or `CashApp/Failed`, and set category `cashapp-processed` | Move to `CashApp/Processed` or `CashApp/Failed`, and set keyword `cashapp-processed` |
| Attachments / nested messages | Raw MIME via `GET /messages/{id}/$value`, so attachments and nested `.eml`/`.msg` arrive intact for the artifact splitter (s34) | `UID FETCH BODY.PEEK[]` returns raw RFC 822 with attachments and nested messages intact |
| Throughput at 2,500 mails/day | About 2 per minute against a limit of 10,000 requests per 10 minutes per mailbox, so not a constraint (verify on first live probe) | Same order of magnitude; fine on one connection |
| OCI egress | Outbound HTTPS 443 from the worker subnet via the NAT gateway to Microsoft endpoints | Outbound TLS 993 from the worker subnet via the NAT gateway |
| Secret storage in OCI Vault | Certificate private key or client secret, tenant ID and client ID stored in Vault as `vault:` references | Password or OAuth refresh token (and client secret) stored in Vault as `vault:` references |

IMAP IDLE is **not used**. The poller polls every N minutes; IDLE would be a push channel and a long-lived connection, and the intake poller is one of exactly two pollers. For the same reason no Graph change-notification webhook is used. The mailbox is read inside the intake poller's loop.

## Recommendation

**Graph if the client is on Microsoft 365, else IMAP.** One adapter is built, never both: each external system has exactly two implementations, the real adapter and the fake. A fake is never presented as a confirmed contract.

## Processed-mail convention

Shared by both adapters:

- On success, move the message to folder `CashApp/Processed`. On failure, move it to `CashApp/Failed`.
- Also set the category (Graph) or keyword (IMAP) `cashapp-processed`, so a message is recognisable even if a move fails.
- **The content hash dedupe in intake's `ingest` is the safety net.** A message whose move failed and is fetched again is recorded as a duplicate, not a new item. The order is ingest then mark, so a crash between them only causes redelivery, never loss.
- Folders are created on first use by the adapter. A person may move a message back into the source folder to reprocess it.
- Messages are never deleted.

## Internal senders

Intake **accepts internal senders**. Forwarded remittances and backlog reprocessing need them; the previous build's exclusion of internal senders blocked backlog reprocessing.

The sender allow/deny list is **runtime configuration, default allow-all**. Proposed keys: `intake.sender_allow: list[str]` (empty means all) and `intake.sender_deny: list[str]` (empty), with exact addresses or `@domain` entries, and deny winning. A denied message is moved to `CashApp/Failed` with a log line and no work item (it never entered the pipeline), so it is never silently lost from the mailbox. The real adapter story registers these keys.

## MailboxSource contract

Built by s06 (interface and `FakeMailboxSource`); `ArtifactSource`, `SourceRef` and module paths are s06's.

```python
# cashapp/pollers/intake/sources.py  (s06 builds it; contract pinned here)
from collections.abc import AsyncIterator
from typing import Literal, Protocol
from cashapp.domain.artifacts import IncomingArtifact   # s34

Outcome = Literal["processed", "failed"]

class MailboxSource(ArtifactSource, Protocol):
    folder: str                                 # source folder, from configuration (Settings), never hard-coded
    def fetch_new(self) -> AsyncIterator[IncomingArtifact]: ...
    async def mark_processed(self, ref: SourceRef, outcome: Outcome) -> None: ...
```

Semantics both adapters and the fake must satisfy:

- `fetch_new() -> AsyncIterator[IncomingArtifact]` yields **one `IncomingArtifact` per message**, never per attachment (s34 splits). Fields: `source_kind="mailbox"`; `content_type="message/rfc822"`; `data` is the raw RFC 822 bytes, unmodified; `filename=f"{safe(message_id)}.eml"`; `received_at` is the server received time (tz-aware UTC); `sender` is the From address, lower-cased; `subject` is the decoded Subject.
- `source_ref` (a `SourceRef`) is opaque to the poller. Graph: the immutable message ID (requested with `Prefer: IdType="ImmutableId"`, so it survives a move). IMAP: `"{folder}:{uidvalidity}:{uid}"`.
- Yields only messages still in `folder` and not marked `cashapp-processed`. Senders denied by `intake.sender_deny` / `intake.sender_allow` are moved to the failed folder and not yielded.
- `mark_processed(ref, "processed")` moves the message to `CashApp/Processed` and sets `cashapp-processed`; `mark_processed(ref, "failed")` moves it to `CashApp/Failed` and sets the same marker. It is idempotent: marking a ref already moved is a no-op, not an error. A move failure raises; the poller logs it and relies on content hash dedupe.
- Never deletes a message.

`FakeMailboxSource` (`cashapp/integrations/mail/fake.py`, s06) is built from a list of `.eml` fixtures, records the `(ref, outcome)` calls, and is marked "unverified against live".

## Configuration split

- Deployment settings (`IntakeSettings.mailbox`, added by the adapter story): `provider: Literal["graph","imap"]`, `mailbox: str`, `source_folder: str = "Inbox"`, `processed_folder: str = "CashApp/Processed"`, `failed_folder: str = "CashApp/Failed"`, and provider credentials as `vault:` references.
- Runtime configuration: `intake.poll_interval_seconds` (existing), `intake.sender_allow`, `intake.sender_deny`.

## Follow-up

The real adapter story, unblocked by the answers to the open questions. It probes the live mailbox first, as non-production as the platform allows, before storing any credential.
