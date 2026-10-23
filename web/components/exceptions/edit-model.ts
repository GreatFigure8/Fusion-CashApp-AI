import { z } from "zod";

import type { Schemas } from "@/lib/api/types";

export type RemittanceExtraction = Schemas["RemittanceExtraction"];
export type ExtractedLine = Schemas["ExtractedLine"];
export type LineKind = Schemas["LineKind"];
export type RequeueBody = Schemas["RequeueIn"];

export const LINE_KINDS = [
  "INVOICE",
  "CREDIT_MEMO",
  "UNKNOWN",
  "BANK_FEE",
  "TARIFF",
  "DISCOUNT",
] as const satisfies readonly LineKind[];

// Drift check: a line kind added to the API without being added here fails type-checking.
type MissingKind = Exclude<LineKind, (typeof LINE_KINDS)[number]>;
const kindListIsComplete: [MissingKind] extends [never] ? true : never = true;
void kindListIsComplete;

const NUMBERLESS_KINDS: readonly LineKind[] = ["BANK_FEE", "TARIFF", "DISCOUNT"];

const MONEY = /^-?\d+\.\d{2}$/;
const moneyOrEmpty = z.string().regex(MONEY, "Use two decimals, e.g. 125.00").or(z.literal(""));

export const editFormSchema = z.object({
  payer_name: z.string(),
  remittance_reference: z.string(),
  payment_amount: moneyOrEmpty,
  currency: z
    .string()
    .regex(/^[A-Z]{3}$/, "Use a 3-letter currency code")
    .or(z.literal("")),
  payment_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, "Use YYYY-MM-DD")
    .or(z.literal("")),
  lines: z.array(
    z
      .object({
        line_no: z.number().int().min(1),
        kind: z.enum(LINE_KINDS),
        transaction_number: z.string(),
        amount_paid: moneyOrEmpty,
        discount_claimed: moneyOrEmpty,
      })
      .superRefine((line, ctx) => {
        if (!NUMBERLESS_KINDS.includes(line.kind) && line.transaction_number.trim() === "") {
          ctx.addIssue({
            code: "custom",
            path: ["transaction_number"],
            message: "An invoice or credit memo needs a number",
          });
        }
      }),
  ),
});

export type EditFormValues = z.infer<typeof editFormSchema>;
export type EditLineValues = EditFormValues["lines"][number];

export const EMPTY_FORM_VALUES: EditFormValues = {
  payer_name: "",
  remittance_reference: "",
  payment_amount: "",
  currency: "",
  payment_date: "",
  lines: [],
};

type ValueField = { value?: string | null; confidence: number };

const text = (field: { value?: string | null }): string => field.value ?? "";

export function toFormValues(final: RemittanceExtraction): EditFormValues {
  return {
    payer_name: text(final.payer_name),
    remittance_reference: text(final.remittance_reference),
    payment_amount: text(final.payment_amount),
    currency: text(final.currency),
    payment_date: text(final.payment_date),
    lines: final.lines.map((line) => ({
      line_no: line.line_no,
      kind: line.kind,
      transaction_number: line.transaction_number,
      amount_paid: line.amount_paid ?? "",
      discount_claimed: line.discount_claimed ?? "",
    })),
  };
}

function setValue<T extends ValueField>(field: T, before: string, after: string): T {
  if (before === after) return field;
  return { ...field, value: after === "" ? null : after, confidence: 1 };
}

/** A new extraction with only the edited fields changed (value, confidence 1, source kept). */
export function applyEdits(
  final: RemittanceExtraction,
  values: EditFormValues,
): RemittanceExtraction {
  const before = toFormValues(final);
  const byNo = new Map(final.lines.map((line) => [line.line_no, line]));
  const beforeByNo = new Map(before.lines.map((line) => [line.line_no, line]));

  const lines: ExtractedLine[] = values.lines.map((edited) => {
    const original = byNo.get(edited.line_no);
    const was = beforeByNo.get(edited.line_no);
    if (!original || !was) {
      return {
        line_no: edited.line_no,
        kind: edited.kind,
        transaction_number: edited.transaction_number,
        amount_paid: edited.amount_paid === "" ? null : edited.amount_paid,
        gross_amount: null,
        discount_claimed: edited.discount_claimed === "" ? null : edited.discount_claimed,
        deduction: null,
        po_number: null,
        sales_order: null,
        ers_reference: null,
        source: null,
        confidence: 1,
      };
    }
    const touched =
      was.kind !== edited.kind ||
      was.transaction_number !== edited.transaction_number ||
      was.amount_paid !== edited.amount_paid ||
      was.discount_claimed !== edited.discount_claimed;
    if (!touched) return original;
    return {
      ...original,
      kind: edited.kind,
      transaction_number: edited.transaction_number,
      amount_paid: edited.amount_paid === "" ? null : edited.amount_paid,
      discount_claimed: edited.discount_claimed === "" ? null : edited.discount_claimed,
      confidence: 1,
    };
  });

  return {
    ...final,
    payer_name: setValue(final.payer_name, before.payer_name, values.payer_name),
    remittance_reference: setValue(
      final.remittance_reference,
      before.remittance_reference,
      values.remittance_reference,
    ),
    payment_amount: setValue(final.payment_amount, before.payment_amount, values.payment_amount),
    currency: setValue(final.currency, before.currency, values.currency),
    payment_date: setValue(final.payment_date, before.payment_date, values.payment_date),
    lines,
  };
}

type Change = { label: string; before: string; after: string | null };

const HEADER_LABELS: ReadonlyArray<readonly [keyof Omit<EditFormValues, "lines">, string]> = [
  ["payer_name", "payer"],
  ["remittance_reference", "reference"],
  ["payment_amount", "amount"],
  ["currency", "currency"],
  ["payment_date", "payment date"],
];

const LINE_LABELS: ReadonlyArray<readonly [keyof Omit<EditLineValues, "line_no">, string]> = [
  ["transaction_number", "invoice"],
  ["amount_paid", "amount"],
  ["discount_claimed", "discount"],
  ["kind", "kind"],
];

function collectChanges(before: EditFormValues, after: EditFormValues): Change[] {
  const changes: Change[] = [];
  for (const [key, label] of HEADER_LABELS) {
    if (before[key] !== after[key]) {
      changes.push({ label, before: before[key], after: after[key] });
    }
  }
  const beforeByNo = new Map(before.lines.map((line) => [line.line_no, line]));
  const afterNos = new Set(after.lines.map((line) => line.line_no));
  for (const line of after.lines) {
    const was = beforeByNo.get(line.line_no);
    if (!was) {
      changes.push({ label: `line ${line.line_no}`, before: "", after: null });
      continue;
    }
    for (const [key, label] of LINE_LABELS) {
      if (was[key] !== line[key]) {
        changes.push({
          label: `line ${line.line_no} ${label}`,
          before: was[key],
          after: line[key],
        });
      }
    }
  }
  for (const line of before.lines) {
    if (!afterNos.has(line.line_no)) {
      changes.push({ label: `line ${line.line_no} removed`, before: "", after: null });
    }
  }
  return changes;
}

function describe(change: Change): string {
  if (change.after === null) {
    return change.label.endsWith("removed") ? change.label : `${change.label} added`;
  }
  const show = (v: string) => (v === "" ? "(empty)" : `'${v}'`);
  return `${change.label} ${show(change.before)} → ${show(change.after)}`;
}

/** "You changed 2 fields: line 3 invoice 'INV1044' → 'INV-1044'; receipt → R-88213." */
export function diffSummary(
  before: EditFormValues,
  after: EditFormValues,
  choices: { receipt?: string; customer?: string },
): { count: number; text: string } {
  const parts = collectChanges(before, after).map(describe);
  if (choices.receipt) parts.push(`receipt → ${choices.receipt}`);
  if (choices.customer) parts.push(`customer → ${choices.customer}`);
  const count = parts.length;
  if (count === 0) return { count, text: "No changes." };
  return {
    count,
    text: `You changed ${count} ${count === 1 ? "field" : "fields"}: ${parts.join("; ")}.`,
  };
}

/** The requeue request. `corrected_extraction` is sent only when a field changed. */
export function buildRequeueBody(args: {
  final: RemittanceExtraction | null;
  before: EditFormValues | null;
  after: EditFormValues | null;
  receiptId?: number;
  customerNumber?: string;
  note: string;
}): RequeueBody {
  const { final, before, after } = args;
  const body: RequeueBody = { note: args.note.trim() };
  if (final && before && after && collectChanges(before, after).length > 0) {
    body.corrected_extraction = applyEdits(final, after);
  }
  if (args.receiptId !== undefined) body.receipt_id = args.receiptId;
  if (args.customerNumber) body.customer_number = args.customerNumber;
  return body;
}

export function isReverseConfirmValid(input: {
  reason: string;
  typed: string;
  receiptNumber: string;
}): boolean {
  const receipt = input.receiptNumber.trim();
  return input.reason.trim() !== "" && receipt !== "" && input.typed.trim() === receipt;
}
