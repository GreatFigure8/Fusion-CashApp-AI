import type {
  ErrorCode,
  ExceptionFilters,
} from "@/app/(shell)/exceptions/_lib/search-params";

/** Pure and client-safe: filter-chip presets over the URL filter state. */

export type ChipId =
  | "all"
  | "ambiguous"
  | "variance"
  | "invoice"
  | "customer"
  | "person"
  | "locked";

export type ExceptionChip = Readonly<{
  id: ChipId;
  label: string;
  codes: readonly ErrorCode[];
  lockedByMe: boolean;
}>;

export const EXCEPTION_CHIPS: readonly ExceptionChip[] = [
  { id: "all", label: "All", codes: [], lockedByMe: false },
  { id: "ambiguous", label: "Ambiguous receipt", codes: ["RECEIPT_AMBIGUOUS"], lockedByMe: false },
  { id: "variance", label: "Amount variance", codes: ["AMOUNT_VARIANCE"], lockedByMe: false },
  { id: "invoice", label: "Invoice not found", codes: ["INVOICE_NOT_FOUND"], lockedByMe: false },
  {
    id: "customer",
    label: "Customer not found",
    codes: ["CUSTOMER_NOT_FOUND"],
    lockedByMe: false,
  },
  {
    id: "person",
    label: "Always a person",
    codes: ["PREPAYMENT", "PO_SO_ERS_ONLY", "DUAL_CURRENCY", "UNGROUNDED"],
    lockedByMe: false,
  },
  { id: "locked", label: "Locked", codes: [], lockedByMe: true },
];

function sameCodes(a: readonly ErrorCode[], b: readonly ErrorCode[]): boolean {
  return a.length === b.length && a.every((code) => b.includes(code));
}

/** The chip whose preset equals the filters' error codes and lock flag, or null for a custom mix. */
export function activeChip(filters: ExceptionFilters): ChipId | null {
  const hit = EXCEPTION_CHIPS.find(
    (chip) => chip.lockedByMe === filters.lockedByMe && sameCodes(chip.codes, filters.errorCodes),
  );
  return hit?.id ?? null;
}

/** Filters with the chip applied: other filters kept, page reset, selected item dropped. */
export function chipFilters(filters: ExceptionFilters, id: ChipId): ExceptionFilters {
  const chip = EXCEPTION_CHIPS.find((c) => c.id === id);
  const { item, ...rest } = filters;
  void item;
  return {
    ...rest,
    errorCodes: chip ? [...chip.codes] : [],
    lockedByMe: chip?.lockedByMe ?? false,
    page: 1,
  };
}
