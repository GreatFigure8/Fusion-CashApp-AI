# s33-spike-mailbox-access: Spike — mailbox access method for the intake poller

- Issue: #33
- Wave: 2 (owns `docs/spikes/mailbox-access.md`)
- breaking: false

## Story

As the builder of the intake poller, I want a written decision on how the poller reads the remittance mailbox(es) and marks processed mail, so that `MailboxSource` is built once against the right protocol.

## Context

Blocked on Jonathan naming the client's mail platform; this spike is built against fakes: it writes the decision framework, a recommended default, and the exact `MailboxSource` contract both options satisfy, so s06 builds the interface and a fake now and the real adapter is a small follow-up once the platform is known. Decision only; no production mailbox changes. Reference doc §1: the previous build ignored internal senders, which blocked backlog reprocessing.

## Acceptance criteria

1. [unit] `docs/spikes/mailbox-access.md` compares Microsoft Graph (app registration, application permission `Mail.ReadWrite` scoped by an application access policy to the remittance mailbox(es), delta queries, move-to-folder) and IMAP (service account, OAuth2 XOAUTH2 or app password, IMAP IDLE not used, UID + move to a `Processed` folder) on: protocol, auth, folders, processed-mail convention, attachments/nested messages, throughput at 2,500 mails/day, OCI egress, and secret storage in OCI Vault.
2. [unit] States the recommended default (Graph if the client is on Microsoft 365, else IMAP) and the processed-mail convention used by both: move to folder `CashApp/Processed` (failures to `CashApp/Failed`), plus a category/flag `cashapp-processed`, and the dedupe on content hash is the safety net if a move fails.
3. [unit] Decides internal senders: intake accepts internal senders (forwarded remittances and backlog reprocessing need it); an allow/deny sender list is runtime configuration, default allow-all.
4. [unit] Pins the `MailboxSource` contract for s06 (and appends a "Mailbox decision" note to `docs/sprints/bmn-open-stories-1-45/s06-intake-poller/story.md` Assumptions): `MailboxSource(ArtifactSource)` with `fetch_new() -> AsyncIterator[IncomingArtifact]` yielding one `IncomingArtifact` per message with the raw RFC 822 bytes (`content_type="message/rfc822"`), `mark_processed(ref, outcome: "processed"|"failed") -> None`, and `folder` from configuration.
5. [unit] Lists the open questions for Jonathan (platform, mailbox names, tenant admin consent) at the top of the document.

## Out of scope

Building either adapter; touching any real mailbox.

## Deps

None. (It annotates s06's story with the decision; s06 depends on this spike, not the reverse.)

## Assumptions

- The client platform is unknown; Microsoft 365 is the more likely default.
