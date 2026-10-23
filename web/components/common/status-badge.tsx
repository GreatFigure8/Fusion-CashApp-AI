import { Pill, type PillTone } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";
import { humanizeEnum } from "@/lib/format";

/**
 * The one place a status value becomes a colour. The maps are typed against the generated API
 * enums, so a status added to the API and missing here is a `tsc` error.
 */
export type StatusToken =
  | "success"
  | "progress"
  | "waiting"
  | "attention"
  | "error"
  | "locked"
  | "neutral";

export const STATUS_TOKENS: {
  item_state: Record<Schemas["ItemState"], StatusToken>;
  payment_status: Record<Schemas["PaymentStatus"], StatusToken>;
  line_status: Record<Schemas["LineStatus"], StatusToken>;
} = {
  item_state: {
    PENDING: "progress",
    IN_PROGRESS: "progress",
    AWAITING_RECEIPT: "waiting",
    ESCALATED: "error",
    DONE: "success",
    ARCHIVED: "neutral",
  },
  payment_status: {
    "payment-success": "success",
    "payment-less-than-total-due-success": "attention",
    "payment-more-than-total-due-success": "attention",
    "payment-previously-applied": "neutral",
    "invoice-not-found": "error",
    "customer-not-found": "error",
    "missing-payment-date": "error",
    "receipt-not-found": "error",
    "zero-amount": "error",
    "payment-apply-failed-system": "error",
    "payment-apply-failed-receipt-closed": "error",
    "payment-apply-failed-zero-balance": "error",
  },
  line_status: {
    "allocation-applied": "success",
    "allocation-applied-short-pay": "attention",
    "allocation-applied-less-than-instruction": "attention",
    "allocation-applied-with-discount": "success",
    "allocation-previously-applied": "neutral",
    "allocation-invoice-not-found": "error",
    "allocation-customer-not-found": "error",
    "allocation-no-remaining-balance": "error",
    "allocation-zero-amount": "error",
    "allocation-missing-payment-date": "error",
    "allocation-no-receipt-match": "error",
    "allocation-apply-failed": "error",
    "allocation-reversed": "neutral",
    "allocation-dry-run": "neutral",
  },
};

/** How each status token renders as a pill. */
export const STATUS_PILL_TONE: Readonly<Record<StatusToken, PillTone>> = {
  success: "ok",
  progress: "accent",
  waiting: "muted",
  attention: "warn",
  error: "err",
  locked: "locked",
  neutral: "muted",
};

export function statusToken(kind: keyof typeof STATUS_TOKENS, value: string): StatusToken {
  const map: Record<string, StatusToken> = STATUS_TOKENS[kind];
  return map[value] ?? "neutral";
}

export function StatusBadge({
  kind,
  value,
  className,
}: {
  kind: keyof typeof STATUS_TOKENS;
  value: string;
  className?: string;
}) {
  const token = statusToken(kind, value);
  return (
    <span data-status={token} className="inline-flex">
      <Pill tone={STATUS_PILL_TONE[token]} dot className={className}>
        {humanizeEnum(value)}
      </Pill>
    </span>
  );
}
