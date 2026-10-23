# s42-notifications: Notifications for escalations and system problems

- Issue: #42
- Wave: 4 (owns `cashapp/services/notifications/`, `cashapp/stations/notify/`, `cashapp/integrations/email/`, `cashapp/data/repositories/notifications.py`)
- breaking: false

## Story

As AR and the operator, I want the right people to hear about escalations and outages as they happen, batched so a flood becomes one message, so that nothing waits unseen and nobody is spammed.

## Context

Sources emit `NotifyEvent` (s18 `cashapp/domain/notifications.py`) through the outbox: item escalations (s18, s14), budget (s36). This story adds the DLQ-growth and outage sources, the consumer, channels and the log. Email via OCI Email Delivery (SMTP); Teams via incoming webhook only if the client uses it (config, default off).

## Acceptance criteria

1. [integration] One Alembic revision creates `NOTIFICATION_LOG` (ID, KIND, SEVERITY, CHANNEL, RECIPIENTS JSON, SUBJECT, EVENT_IDS JSON, ITEM_COUNT, SENT_AT, STATUS (sent|failed|suppressed), ERROR).
2. [unit] `NotificationChannel` Protocol `send(recipients, subject, body_text, body_html|None) -> None`; `SmtpEmailChannel` (OCI Email Delivery SMTP, credentials from settings/Vault, TLS) and `TeamsWebhookChannel`; `FakeChannel` for tests. Recipients and channels per kind come from `config.notifications().recipients` (`{kind: {channel: [addresses|webhook]}}`).
3. [integration] `NotifyConsumer` (`cashapp/stations/notify/`, `ROLE = RoleSpec("notify", "consumer", build)`) consumes the notify topic and batches: events of the same kind within `notifications.batch_window_seconds` are combined into one message ("12 items escalated in the last 5 minutes" with a list of item ids, error codes and links `/exceptions?item=<id>`); critical events (outage) send immediately; at most one message per kind per window (test with 50 events → 1 message).
4. [unit] Sources added here: DLQ growth — after each outbox relay batch / worker health tick, `BusHealth.snapshot()` DLQ depth increase over the last notified value emits `NotifyEvent(kind="dlq_growth")`; outage — `FusionError(FUSION_TRANSIENT)` or `LlmError(LLM_TRANSIENT)` rates above a threshold within 5 minutes (counter in the worker host's metrics) emit `NotifyEvent(kind="outage")`; both via the outbox, deduplicated per window.
5. [unit] Every send (and suppression or failure) writes a `NOTIFICATION_LOG` row; message bodies contain item ids, codes and counts only — no remittance content or payer names (test with sentinel values).
6. [api] `GET /notifications/log?kind=&from=&to=` (`reports:read`) → paged log rows.
7. [unit] `send_report_email(recipients, subject, body, attachments: list[(filename, bytes, content_type)])` is public for s41's daily summary.

## Out of scope

Configuration UI for recipients (the configuration screen exposes the `notifications.recipients` key generically in s21).

## Deps

- s18-auto-fix-engine — `NotifyEvent`, notify topic name. plannable.
- s03-pipeline-runtime — `EventBus.subscribe`, `emit`, `BusHealth`. plannable.
- s30-worker-host — health tick hook (`HealthTickHook` list in `cashapp/workers/hooks.py`). plannable.
- s28-runtime-config-service — `config.notifications()`. plannable.
- s27-settings-secrets-wiring — `smtp` settings group (host, port, username, password: SecretStr, from_address) — add. plannable.

## Assumptions

- Teams is off unless configured; email is the default channel.
