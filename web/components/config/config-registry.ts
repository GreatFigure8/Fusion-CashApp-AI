import type { Schemas } from "@/lib/api/types";

export type ConfigTabId =
  | "access"
  | "polling"
  | "matching"
  | "retries"
  | "models"
  | "retention"
  | "aliases";

export type EditorKind =
  | "number"
  | "nullable-days"
  | "tolerance-table"
  | "bank-fee-bands"
  | "backoff-list"
  | "max-attempts"
  | "model-role"
  | "group-roles"
  | "switch"
  | "text"
  | "decimal-nullable"
  | "json";

export type ConfigUi = Readonly<{
  tab: ConfigTabId;
  label: string;
  unit?: string;
  editor: EditorKind;
  order: number;
  section?: "main" | "other";
  /** Numeric bounds mirrored from the API for fast feedback; the API stays the authority. */
  range?: Readonly<{ min: number; max?: number; integer: boolean }>;
  /** Regular expression source for `text` editors. */
  pattern?: string;
}>;

/** Design §6 order. */
export const CONFIG_TABS: readonly { id: ConfigTabId; label: string }[] = [
  { id: "access", label: "Access" },
  { id: "polling", label: "Polling" },
  { id: "matching", label: "Matching" },
  { id: "retries", label: "Retries & aging" },
  { id: "models", label: "Models" },
  { id: "retention", label: "Retention" },
  { id: "aliases", label: "Payer aliases" },
];

export const GROUP_ROLE_KEY = "access.group_role_map";

/** A fixed note shown above a tab's settings. */
export const CONFIG_TAB_NOTES: Partial<Record<ConfigTabId, string>> = {
  models: "Claude Fable models are not allowed (zero data retention).",
};

const secondsRange = { min: 1, integer: true } as const;
const positiveRange = { min: 1, integer: true } as const;
const daysRange = { min: 0, integer: true } as const;

export const CONFIG_UI: Readonly<Record<string, ConfigUi>> = {
  [GROUP_ROLE_KEY]: {
    tab: "access",
    label: "Group to role mapping",
    editor: "group-roles",
    order: 1,
  },

  "intake.poll_interval_seconds": {
    tab: "polling",
    label: "Intake poll interval",
    unit: "s",
    editor: "number",
    order: 1,
    range: secondsRange,
  },
  "receipt_watcher.poll_interval_seconds": {
    tab: "polling",
    label: "Receipt watcher poll interval",
    unit: "s",
    editor: "number",
    order: 2,
    range: secondsRange,
  },

  "matching.date_window_days": {
    tab: "matching",
    label: "Receipt date window",
    unit: "days",
    editor: "number",
    order: 1,
    range: daysRange,
  },
  "matching.tolerances": {
    tab: "matching",
    label: "Amount tolerances",
    editor: "tolerance-table",
    order: 2,
  },
  "matching.bank_fee_bands": {
    tab: "matching",
    label: "Bank fee bands",
    editor: "bank-fee-bands",
    order: 3,
  },
  "matching.min_score": {
    tab: "matching",
    label: "Minimum receipt score",
    editor: "number",
    order: 4,
    range: { min: 0, integer: false },
  },
  "matching.scorer_weights": {
    tab: "matching",
    label: "Scorer weights",
    editor: "json",
    order: 5,
  },
  "discount.enabled": {
    tab: "matching",
    label: "Take earned discounts",
    editor: "switch",
    order: 6,
  },

  "retries.max_attempts": {
    tab: "retries",
    label: "Maximum auto-fix attempts",
    editor: "max-attempts",
    order: 1,
  },
  "retries.backoff_seconds": {
    tab: "retries",
    label: "Retry backoff",
    unit: "s",
    editor: "backoff-list",
    order: 2,
  },
  "aging.awaiting_receipt_max_days": {
    tab: "retries",
    label: "Awaiting receipt, maximum age",
    unit: "days",
    editor: "number",
    order: 3,
    range: daysRange,
  },
  "escalation.min_extraction_confidence": {
    tab: "retries",
    label: "Minimum extraction confidence",
    editor: "number",
    order: 4,
    range: { min: 0, max: 1, integer: false },
  },
  "extraction.fanin_timeout_seconds": {
    tab: "retries",
    label: "Reader fan-in timeout",
    unit: "s",
    editor: "number",
    order: 5,
    range: secondsRange,
  },
  "concurrency.per_stage": {
    tab: "retries",
    label: "Concurrency per stage",
    editor: "json",
    order: 10,
    section: "other",
  },
  "concurrency.apply_per_receipt": {
    tab: "retries",
    label: "Concurrent applies per receipt",
    editor: "number",
    order: 11,
    section: "other",
    range: positiveRange,
  },
  "locks.lease_minutes": {
    tab: "retries",
    label: "Item lock lease",
    unit: "min",
    editor: "number",
    order: 12,
    section: "other",
    range: positiveRange,
  },
  "backlog.rate_limit_per_minute": {
    tab: "retries",
    label: "Backlog release rate",
    unit: "per min",
    editor: "number",
    order: 13,
    section: "other",
    range: positiveRange,
  },
  "notifications.recipients": {
    tab: "retries",
    label: "Notification recipients",
    editor: "json",
    order: 14,
    section: "other",
  },
  "notifications.batch_window_seconds": {
    tab: "retries",
    label: "Notification batch window",
    unit: "s",
    editor: "number",
    order: 15,
    section: "other",
    range: secondsRange,
  },
  "notifications.outage_threshold": {
    tab: "retries",
    label: "Outage error threshold",
    editor: "number",
    order: 16,
    section: "other",
    range: positiveRange,
  },
  "notifications.outage_window_seconds": {
    tab: "retries",
    label: "Outage detection window",
    unit: "s",
    editor: "number",
    order: 17,
    section: "other",
    range: { min: 60, integer: true },
  },
  "reports.daily_summary_cutover": {
    tab: "retries",
    label: "Daily summary cutover",
    editor: "text",
    order: 18,
    section: "other",
    pattern: "^\\d{2}:\\d{2}$",
  },

  "models.reader_a": { tab: "models", label: "Reader A", editor: "model-role", order: 1 },
  "models.reader_b": { tab: "models", label: "Reader B", editor: "model-role", order: 2 },
  "models.adjudicator": { tab: "models", label: "Adjudicator", editor: "model-role", order: 3 },
  "models.workhorse": { tab: "models", label: "Workhorse", editor: "model-role", order: 4 },
  "budget.daily_usd": {
    tab: "models",
    label: "Daily LLM budget",
    unit: "USD",
    editor: "decimal-nullable",
    order: 5,
  },

  "retention.raw_artifact_days": {
    tab: "retention",
    label: "Keep raw artifacts",
    unit: "days",
    editor: "nullable-days",
    order: 1,
  },
  "retention.extraction_days": {
    tab: "retention",
    label: "Keep extraction data",
    unit: "days",
    editor: "nullable-days",
    order: 2,
  },
  "retention.history_payload_days": {
    tab: "retention",
    label: "Keep history payloads",
    unit: "days",
    editor: "nullable-days",
    order: 3,
  },
};

/** A key the registry doesn't know still gets a JSON editor, so no API key is unreachable. */
export function uiFor(key: string): ConfigUi {
  return (
    CONFIG_UI[key] ?? {
      tab: "retries",
      label: key,
      editor: "json",
      order: 1000,
      section: "other",
    }
  );
}

/** The entries shown on a tab, in registry order (unknown keys last, by name). */
export function keysForTab(
  entries: readonly Schemas["ConfigEntry"][],
  tab: ConfigTabId,
): Schemas["ConfigEntry"][] {
  return entries
    .filter((e) => uiFor(e.key).tab === tab)
    .sort((a, b) => uiFor(a.key).order - uiFor(b.key).order || a.key.localeCompare(b.key));
}

/** Sort position of a key for saves: tab order, then row order, the group-role map last. */
export function saveOrder(key: string): number {
  if (key === GROUP_ROLE_KEY) return Number.MAX_SAFE_INTEGER;
  const tabIndex = CONFIG_TABS.findIndex((t) => t.id === uiFor(key).tab);
  return tabIndex * 10_000 + uiFor(key).order;
}

/** The API's error codes, for the max-attempts editor. The API rejects any code it doesn't know. */
export const ERROR_CODES: readonly string[] = [
  "RECEIPT_NOT_YET_AVAILABLE",
  "RECEIPT_AMBIGUOUS",
  "RECEIPT_RESERVED",
  "AMOUNT_VARIANCE",
  "CUSTOMER_NOT_FOUND",
  "CUSTOMER_MULTIPLE_ACCOUNTS",
  "INVOICE_NOT_FOUND",
  "INVOICE_CLOSED",
  "INVOICE_CURRENCY_MISMATCH",
  "INVOICE_STATUS_INVALID",
  "INVALID_INVOICE_NUMBER",
  "INVALID_DATE",
  "INVALID_CURRENCY",
  "MISSING_PAYMENT_DATE",
  "ZERO_AMOUNT_LINE",
  "LOW_EXTRACTION_CONFIDENCE",
  "EXTRACTION_FAILED",
  "CLASSIFICATION_FAILED",
  "LLM_REFUSAL",
  "LLM_TRANSIENT",
  "UNSUPPORTED_ARTIFACT",
  "FUSION_OVERAPPLY",
  "FUSION_ALREADY_APPLIED",
  "FUSION_LOCKED",
  "FUSION_TRANSIENT",
  "FUSION_GL_DATE",
  "FUSION_FAULT",
  "FUSION_DISCOUNT_REJECTED",
  "FUSION_WRITE_DISABLED",
  "WRITE_BACK_FAILED",
  "REVERSAL_FAILED",
  "AGED_OUT",
  "PREPAYMENT",
  "PO_SO_ERS_ONLY",
  "DUAL_CURRENCY",
  "UNGROUNDED",
  "SYSTEM_DEAD_LETTER",
];

export const KNOWN_MODEL_IDS: readonly string[] = [
  "claude-opus-5-5",
  "claude-haiku-5-5",
  "cohere.command-a-vision",
];

export const ROLES = [
  "ADMIN",
  "OPERATOR",
  "REVERSER",
  "VIEWER",
] as const satisfies readonly Schemas["Role"][];

export const EFFORTS = ["low", "medium", "high", "max"] as const;
