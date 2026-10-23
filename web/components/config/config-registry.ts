import type { Schemas } from "@/lib/api/types";

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
  | "secret-ref"
  | "text"
  | "decimal-nullable"
  | "json";

export type ConfigUi = Readonly<{
  label: string;
  unit?: string;
  editor: EditorKind;
  order: number;
  /** Numeric bounds mirrored from the API for fast feedback; the API stays the authority. */
  range?: Readonly<{ min: number; max?: number; integer: boolean }>;
  /** Regular expression source for `text` editors. */
  pattern?: string;
}>;

export const GROUP_ROLE_KEY = "access.group_role_map";

const secondsRange = { min: 1, integer: true } as const;
const positiveRange = { min: 1, integer: true } as const;
const daysRange = { min: 0, integer: true } as const;

export const CONFIG_UI: Readonly<Record<string, ConfigUi>> = {
  [GROUP_ROLE_KEY]: {
    label: "Group to role mapping",
    editor: "group-roles",
    order: 1,
  },

  "intake.poll_interval_seconds": {
    label: "Intake poll interval",
    unit: "s",
    editor: "number",
    order: 1,
    range: secondsRange,
  },
  "receipt_watcher.poll_interval_seconds": {
    label: "Receipt watcher poll interval",
    unit: "s",
    editor: "number",
    order: 2,
    range: secondsRange,
  },

  "matching.date_window_days": {
    label: "Receipt date window",
    unit: "days",
    editor: "number",
    order: 1,
    range: daysRange,
  },
  "matching.tolerances": {
    label: "Amount tolerances",
    editor: "tolerance-table",
    order: 2,
  },
  "matching.bank_fee_bands": {
    label: "Bank fee bands",
    editor: "bank-fee-bands",
    order: 3,
  },
  "matching.min_score": {
    label: "Minimum receipt score",
    editor: "number",
    order: 4,
    range: { min: 0, integer: false },
  },
  "matching.scorer_weights": {
    label: "Scorer weights",
    editor: "json",
    order: 5,
  },
  "discount.enabled": {
    label: "Take earned discounts",
    editor: "switch",
    order: 6,
  },

  "retries.max_attempts": {
    label: "Maximum auto-fix attempts",
    editor: "max-attempts",
    order: 1,
  },
  "retries.backoff_seconds": {
    label: "Retry backoff",
    unit: "s",
    editor: "backoff-list",
    order: 2,
  },
  "aging.awaiting_receipt_max_days": {
    label: "Awaiting receipt, maximum age",
    unit: "days",
    editor: "number",
    order: 3,
    range: daysRange,
  },
  "escalation.min_extraction_confidence": {
    label: "Minimum extraction confidence",
    editor: "number",
    order: 4,
    range: { min: 0, max: 1, integer: false },
  },
  "extraction.fanin_timeout_seconds": {
    label: "Reader fan-in timeout",
    unit: "s",
    editor: "number",
    order: 5,
    range: secondsRange,
  },
  "concurrency.per_stage": {
    label: "Concurrency per stage",
    editor: "json",
    order: 10,
  },
  "concurrency.apply_per_receipt": {
    label: "Concurrent applies per receipt",
    editor: "number",
    order: 11,
    range: positiveRange,
  },
  "locks.lease_minutes": {
    label: "Item lock lease",
    unit: "min",
    editor: "number",
    order: 12,
    range: positiveRange,
  },
  "backlog.rate_limit_per_minute": {
    label: "Backlog release rate",
    unit: "per min",
    editor: "number",
    order: 13,
    range: positiveRange,
  },
  "notifications.recipients": {
    label: "Notification recipients",
    editor: "json",
    order: 14,
  },
  "notifications.batch_window_seconds": {
    label: "Notification batch window",
    unit: "s",
    editor: "number",
    order: 15,
    range: secondsRange,
  },
  "notifications.outage_threshold": {
    label: "Outage error threshold",
    editor: "number",
    order: 16,
    range: positiveRange,
  },
  "notifications.outage_window_seconds": {
    label: "Outage detection window",
    unit: "s",
    editor: "number",
    order: 17,
    range: { min: 60, integer: true },
  },
  "reports.daily_summary_cutover": {
    label: "Daily summary cutover",
    editor: "text",
    order: 18,
    pattern: "^\\d{2}:\\d{2}$",
  },

  "models.reader_a": { label: "Reader A", editor: "model-role", order: 1 },
  "models.reader_b": { label: "Reader B", editor: "model-role", order: 2 },
  "models.adjudicator": { label: "Adjudicator", editor: "model-role", order: 3 },
  "models.workhorse": { label: "Workhorse", editor: "model-role", order: 4 },
  "budget.daily_usd": {
    label: "Daily LLM budget",
    unit: "USD",
    editor: "decimal-nullable",
    order: 5,
  },

  "retention.raw_artifact_days": {
    label: "Keep raw artifacts",
    unit: "days",
    editor: "nullable-days",
    order: 1,
  },
  "retention.extraction_days": {
    label: "Keep extraction data",
    unit: "days",
    editor: "nullable-days",
    order: 2,
  },
  "retention.history_payload_days": {
    label: "Keep history payloads",
    unit: "days",
    editor: "nullable-days",
    order: 3,
  },
};

/** Editor chosen from the shape of a value, for keys the hint table does not know. */
export function editorFor(entry: { value: unknown; secret_ref?: boolean }): EditorKind {
  if (entry.secret_ref) return "secret-ref";
  switch (typeof entry.value) {
    case "number":
      return "number";
    case "boolean":
      return "switch";
    case "string":
      return "text";
    default:
      return "json";
  }
}

/** Editor hints for an entry; unknown keys get a label of their own name and a type-based editor. */
export function uiForEntry(entry: {
  key: string;
  value: unknown;
  secret_ref?: boolean;
}): ConfigUi {
  const hint = CONFIG_UI[entry.key];
  if (entry.secret_ref) {
    return { label: entry.key, ...hint, editor: "secret-ref", order: hint?.order ?? 1000 };
  }
  return hint ?? { label: entry.key, editor: editorFor(entry), order: 1000 };
}

/** Hints by key alone (history, review): unknown keys format as JSON. */
export function uiFor(key: string): ConfigUi {
  return CONFIG_UI[key] ?? { label: key, editor: "json", order: 1000 };
}

/** The entries of one group, in hint order (unknown keys last, by name). */
export function entriesForGroup(
  entries: readonly Schemas["ConfigEntry"][],
  group: string,
): Schemas["ConfigEntry"][] {
  return entries
    .filter((e) => e.group === group)
    .sort((a, b) => uiFor(a.key).order - uiFor(b.key).order || a.key.localeCompare(b.key));
}

/** Sort position of a key for saves: hint order; the group-role map last. */
export function saveOrder(key: string): number {
  if (key === GROUP_ROLE_KEY) return Number.MAX_SAFE_INTEGER;
  return uiFor(key).order;
}

/** A Vault secret OCID, the only thing a `secret_ref` setting may hold. */
export const VAULT_SECRET_OCID_PREFIX = "ocid1.vaultsecret.";

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
