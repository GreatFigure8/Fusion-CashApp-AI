# Plan: s33-spike-mailbox-access

Issue #33. Wave 2. Decision-only spike: one design document, one note appended to s06's story, and
a doc-content test. No adapter code, no settings or config keys, no migration, no contact with any
real mailbox. Follows research.md: "Spikes and stories blocked on credentials are planned against
fakes"; every external system gets exactly two implementations, the real adapter and the fake; a fake
is never presented as a confirmed contract.

## Files to touch

| Path | Change |
|---|---|
| `docs/spikes/mailbox-access.md` | new: the decision document (owned by this story) |
| `docs/sprints/bmn-open-stories-1-45/s06-intake-poller/story.md` | append a "Mailbox decision" bullet under `## Assumptions` only. Nothing else in the file changes. This is the only file shared with s06, and the change is append-only. |
| `api/tests/docs/__init__.py` | new empty package marker (create only if missing) |
| `api/tests/docs/test_spike_mailbox_access.py` | new: the AC tests (written and run at step 5 only) |

No code in `api/src/`, no `pyproject.toml` or lockfile edits, no Alembic revision, no `config_keys.py`
or `Settings` edits. s06 owns `cashapp/integrations/mail/` and `cashapp/pollers/intake/sources.py`.
s27 owns `IntakeSettings`. s28 owns the `config_keys` registry. The keys this spike proposes are named
in the document and the s06 note, and the story that builds the real adapter adds them.

## Standards followed

- CLAUDE.md: integrations behind interfaces (`MailboxSource`); hosted only in OCI Ashburn (the
  mailbox call is outbound egress from the worker, and nothing is hosted elsewhere); secrets from OCI
  Vault through s27's `vault:<ocid>` references; customer PII stays inside OCI (raw RFC 822 is stored
  in Object Storage by s06, and is never logged); intake dedupe on content hash; poller 1 of exactly 2
  (the mailbox is read inside the intake poller's loop, so there is no new poller and no push
  subscription/webhook listener).
- Reference doc §1: up to about 2,500 remittance emails on a peak day; the work surface was mail
  folders; reprocess the backlog through the same pipeline. The story context records that the
  previous build ignored internal senders, which blocked backlog reprocessing.
- `python-web-app:building-python-web-apps`: tests under `api/tests/`, pure and I/O-free (they read
  repo files only); external SDKs isolated behind a service/integration module.
- No client or customer names from the prior engagement. The document names the old tools only
  generically ("a shared queue tool", "personal mailboxes").

## Document outline: `docs/spikes/mailbox-access.md`

1. **Open questions for Jonathan** (first H2, AC5). Includes: the client's mail platform (Microsoft 365
   / Exchange Online, Google Workspace, or on-prem Exchange / other IMAP); the remittance mailbox
   address(es) and source folder; who grants tenant admin consent (Graph) or provisions the service
   account / OAuth client (IMAP); whether the `CashApp/Processed` and `CashApp/Failed` folders may be
   created in the shared mailbox; backlog folder(s) to reprocess.
2. **Status**: Decision: provisional. Unverified against a live mailbox. Built against
   `FakeMailboxSource`.
3. **Comparison table** (AC1). Columns: Microsoft Graph | IMAP. Rows, in this order and with these exact
   labels (the test checks each): Protocol; Auth; Folders; Processed-mail convention;
   Attachments / nested messages; Throughput at 2,500 mails/day; OCI egress; Secret storage in OCI Vault.
   - Graph: HTTPS REST `graph.microsoft.com/v1.0`; app registration with application permission
     `Mail.ReadWrite`, restricted by an Exchange **application access policy** (RBAC for Applications) to
     a mail-enabled security group containing only the remittance mailbox(es); client-credentials flow
     with a certificate (preferred) or client secret; `mailFolders/{id}/messages/delta` delta queries
     with the `deltaLink` kept in the DB; `POST /messages/{id}/move` to the destination folder; raw MIME
     via `GET /messages/{id}/$value`, so attachments and nested `.eml`/`.msg` come out intact for s34;
     2,500/day is about 2 per minute against a limit of 10,000 requests per 10 minutes per mailbox, so
     not a constraint; outbound HTTPS 443 from the worker subnet via the NAT gateway to Microsoft
     endpoints; the certificate private key or client secret, tenant ID and client ID go in Vault as
     `vault:` references.
   - IMAP: IMAP4rev1 over TLS 993 (`aioimaplib`, or `imaplib` in `asyncio.to_thread`); service
     account with OAuth2 SASL `XOAUTH2` (Microsoft 365 and Google have turned off basic auth) or an
     app password where the platform still allows it; IMAP IDLE is **not used**, because the poller polls
     every N minutes and IDLE would be a push channel and a long-lived connection (NN5); `UID SEARCH`
     on the source folder, `UID FETCH BODY.PEEK[]` for raw RFC 822, `UID MOVE` (RFC 6851; fallback
     `COPY` + `\Deleted` + `UID EXPUNGE`) to `CashApp/Processed`; `UIDVALIDITY` stored with the last
     UID; throughput is the same order and fine on one connection; outbound TLS 993 egress via the NAT
     gateway; password or refresh token in Vault.
4. **Recommendation** (AC2): **Graph if the client is on Microsoft 365, else IMAP.** One adapter is
   built, never both (research.md: two implementations per interface, the real one and the fake).
5. **Processed-mail convention** (AC2), shared by both: on success, move to folder `CashApp/Processed`;
   on failure, move to `CashApp/Failed`. Also set the category (Graph) or keyword (IMAP) `cashapp-processed`
   so a message is recognisable even if a move fails. **The content-hash dedupe in s06's `ingest` is the
   safety net:** a message whose move failed and is fetched again is recorded as a duplicate, not a new
   item. The order is ingest then mark, so a crash between them only causes redelivery, never loss.
   Folders are created on first use by the adapter. A person may move a message back into the source
   folder to reprocess it.
6. **Internal senders** (AC3): intake **accepts internal senders**, because forwarded remittances and
   backlog reprocessing need them; the previous build's exclusion of internal senders blocked backlog
   reprocessing. The sender allow/deny list is **runtime configuration, default allow-all**. The proposed
   keys are `intake.sender_allow: list[str]` (empty = all) and `intake.sender_deny: list[str]` (empty), with
   exact addresses or `@domain` entries and deny winning. A denied message is moved to
   `CashApp/Failed` with a history-free log line (no work item, because it never entered the pipeline),
   so it's never silently lost from the mailbox.
7. **`MailboxSource` contract** (AC4), pinned below and copied verbatim into the document.
8. **Configuration split**: deployment settings (s27 `IntakeSettings.mailbox`, added by the adapter
   story): `provider: Literal["graph","imap"]`, `mailbox: str`, `source_folder: str = "Inbox"`,
   `processed_folder: str = "CashApp/Processed"`, `failed_folder: str = "CashApp/Failed"`, and
   provider credentials as `vault:` references. Runtime config (s28): `intake.poll_interval_seconds`
   (existing), `intake.sender_allow`, `intake.sender_deny`.
9. **Follow-up**: the real adapter story, unblocked by the answers to section 1. It probes the live
   mailbox first, as non-production as the platform allows.

## Interfaces provided (pinned)

These are consumed by s06 (interface and `FakeMailboxSource`), s35 (backlog reprocessing) and the
follow-up real adapter. `ArtifactSource`, `SourceRef` and the module paths are s06's. This spike fixes
only the mail-specific semantics.

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
- `fetch_new()` yields **one `IncomingArtifact` per message**, never per attachment (s34 splits).
  Field values: `source_kind="mailbox"`; `content_type="message/rfc822"`; `data` = raw RFC 822 bytes,
  unmodified; `filename=f"{safe(message_id)}.eml"`; `received_at` = server received time (tz-aware
  UTC); `sender` = the From address, lower-cased; `subject` = the decoded Subject.
- `source_ref` (a `SourceRef`) is opaque to the poller. Graph: the immutable message ID (requested
  with `Prefer: IdType="ImmutableId"`, so it survives a move). IMAP: `"{folder}:{uidvalidity}:{uid}"`.
- Yields only messages still in `folder` and not marked `cashapp-processed`. Senders denied by
  `intake.sender_deny`/`sender_allow` are moved to the failed folder and not yielded.
- `mark_processed(ref, "processed")` moves the message to `CashApp/Processed` and sets `cashapp-processed`;
  `"failed"` moves it to `CashApp/Failed` and sets the same marker. It's idempotent: marking a ref already moved
  is a no-op, not an error. A move failure raises; the poller logs it and relies on content-hash dedupe.
- Never deletes a message.

`FakeMailboxSource` (s06, `cashapp/integrations/mail/fake.py`) is built from a list of `.eml` fixtures
and records the `(ref, outcome)` calls. It's marked "unverified against live".

## s06 note (appended verbatim under s06 `## Assumptions`)

> - **Mailbox decision (s33, `docs/spikes/mailbox-access.md`):** `MailboxSource(ArtifactSource)` with
>   `folder` from configuration, `fetch_new() -> AsyncIterator[IncomingArtifact]` yielding one
>   artifact per message (raw RFC 822 bytes, `content_type="message/rfc822"`, `source_kind="mailbox"`),
>   and `mark_processed(ref, outcome: "processed"|"failed") -> None` moving to `CashApp/Processed` /
>   `CashApp/Failed` plus the `cashapp-processed` marker; content-hash dedupe is the safety net. Internal
>   senders are accepted; sender allow/deny is runtime config (`intake.sender_allow`/`sender_deny`,
>   default allow-all), added with the real adapter. Recommended adapter: Graph if Microsoft 365, else IMAP;
>   provisional until Jonathan names the platform.

## Migrations

None.

## TEST PLAN

All tests are in `api/tests/docs/test_spike_mailbox_access.py`. They're pure file reads with no
markers, resolve the repo root from `Path(__file__).parents[3]`, and are written and run at step 5
only. One helper, `_doc()`, reads the document, and `_section(h2)` extracts one H2 section.

| AC | Test | Asserts |
|---|---|---|
| 1 | `test_comparison_covers_graph_and_imap_on_every_dimension` | The comparison table has a `Microsoft Graph` and an `IMAP` column and a row for each of the 8 labels: Protocol, Auth, Folders, Processed-mail convention, Attachments / nested messages, Throughput at 2,500 mails/day, OCI egress, Secret storage in OCI Vault. No cell in those rows is empty. |
| 1 | `test_comparison_names_the_required_mechanisms` | The document contains `Mail.ReadWrite`, `application access policy`, `delta`, `XOAUTH2`, `app password`, `IDLE` (stated as not used), `UID` and `Processed`. |
| 2 | `test_recommends_graph_for_m365_else_imap_with_shared_convention` | The Recommendation section states Graph if Microsoft 365, else IMAP. The convention section contains `CashApp/Processed`, `CashApp/Failed`, `cashapp-processed` and "content hash" as the safety net. |
| 3 | `test_internal_senders_accepted_and_sender_list_is_runtime_config_default_allow_all` | The Internal senders section says internal senders are accepted, mentions backlog reprocessing, and names `intake.sender_allow`/`intake.sender_deny` as runtime configuration with default allow-all. |
| 4 | `test_pins_mailbox_source_contract` | The document contains `MailboxSource(ArtifactSource`, `fetch_new() -> AsyncIterator[IncomingArtifact]`, `message/rfc822`, `mark_processed(ref`, `"processed"`, `"failed"` and `folder`. |
| 4 | `test_s06_story_carries_mailbox_decision_note` | The `## Assumptions` section of s06's `story.md` contains `Mailbox decision`, `message/rfc822` and `docs/spikes/mailbox-access.md`. Its acceptance criteria are byte-identical to `git show HEAD:<path>` before the note, so the edit is append-only. |
| 5 | `test_open_questions_come_first` | The first H2 is `Open questions for Jonathan` and mentions the platform, the mailbox names and the tenant admin consent. |
| (rule) | `test_no_prior_client_names` | The document contains none of the case-insensitive denylist terms read from the existing redaction denylist if s43/s29 provides one. Otherwise the check is skipped with a reason. It never hard-codes the names. |

## Risks

- **The platform is unknown.** The comparison is written from vendor knowledge and not fetched live
  (research.md assumption). Graph throttling numbers and IMAP MOVE support are marked "verify on
  first live probe" in the document.
- **s06 may be planned before this note lands.** The contract above matches s06's AC2 exactly, so
  nothing in s06's plan has to change. The note only adds the sender keys and the folder names.
- **Sender keys aren't registered yet.** The proposed `intake.sender_*` keys aren't added to s28's
  registry by this story, because no code reads them until the real adapter exists (logged deviation:
  the story says "is runtime configuration"; this spike decides that and names the keys, and the adapter
  story registers them).
- **Graph application access policy** needs Exchange admin rights; until it's applied, the
  `Mail.ReadWrite` grant is tenant-wide. The document flags this as a precondition before any
  credential is stored.
- The `test_no_prior_client_names` denylist source may not exist yet, so the test skips rather than
  hard-coding names (CLAUDE.md forbids putting them in tests).

## Assumptions (deviations logged)

- No code ships in this spike. The `MailboxSource` Protocol itself is built by s06.
- The tests live in a new `api/tests/docs/` folder to keep them file-disjoint from other stories.
- The `IntakeSettings.mailbox` sub-model and the sender keys are named here and added by the real
  adapter story, not by s27 or s28 now.
