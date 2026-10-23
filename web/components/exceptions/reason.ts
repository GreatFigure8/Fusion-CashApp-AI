import type { ErrorCode } from "@/app/(shell)/exceptions/_lib/search-params";
import type { PillTone } from "@/components/common/pill";
import { humanizeEnum } from "@/lib/format";

/**
 * Pure: how an error code reads on a pill. The map is exhaustive, so a code added to the API and
 * missing here is a `tsc` error.
 */
export const REASON_TONE: Readonly<Record<ErrorCode, PillTone>> = {
  // Always a person.
  PREPAYMENT: "locked",
  PO_SO_ERS_ONLY: "locked",
  DUAL_CURRENCY: "locked",
  UNGROUNDED: "locked",
  CUSTOMER_MULTIPLE_ACCOUNTS: "locked",
  // Not found, failed and fault codes.
  CUSTOMER_NOT_FOUND: "err",
  INVOICE_NOT_FOUND: "err",
  INVOICE_CLOSED: "err",
  INVOICE_CURRENCY_MISMATCH: "err",
  INVOICE_STATUS_INVALID: "err",
  INVALID_INVOICE_NUMBER: "err",
  INVALID_DATE: "err",
  INVALID_CURRENCY: "err",
  MISSING_PAYMENT_DATE: "err",
  ZERO_AMOUNT_LINE: "err",
  EXTRACTION_FAILED: "err",
  CLASSIFICATION_FAILED: "err",
  LLM_REFUSAL: "err",
  UNSUPPORTED_ARTIFACT: "err",
  FUSION_FAULT: "err",
  FUSION_DISCOUNT_REJECTED: "err",
  FUSION_WRITE_DISABLED: "err",
  WRITE_BACK_FAILED: "err",
  REVERSAL_FAILED: "err",
  AGED_OUT: "err",
  SYSTEM_DEAD_LETTER: "err",
  // Ambiguous, variance, low-confidence and transient codes.
  RECEIPT_AMBIGUOUS: "warn",
  RECEIPT_RESERVED: "warn",
  RECEIPT_NOT_YET_AVAILABLE: "warn",
  AMOUNT_VARIANCE: "warn",
  LOW_EXTRACTION_CONFIDENCE: "warn",
  LLM_TRANSIENT: "warn",
  FUSION_OVERAPPLY: "warn",
  FUSION_ALREADY_APPLIED: "warn",
  FUSION_LOCKED: "warn",
  FUSION_TRANSIENT: "warn",
  FUSION_GL_DATE: "warn",
};

const SHORT_LABEL: Readonly<Partial<Record<ErrorCode, string>>> = {
  RECEIPT_AMBIGUOUS: "Ambiguous receipt",
  AMOUNT_VARIANCE: "Amount variance",
  INVOICE_NOT_FOUND: "Invoice not found",
  CUSTOMER_NOT_FOUND: "Customer not found",
  PREPAYMENT: "Prepayment",
  LOW_EXTRACTION_CONFIDENCE: "Low confidence",
  PO_SO_ERS_ONLY: "PO reference only",
};

export function reasonLabel(code: ErrorCode): string {
  return SHORT_LABEL[code] ?? humanizeEnum(code);
}
