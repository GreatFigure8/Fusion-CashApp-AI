import { z } from "zod";

import { ROLES, type EditorKind, type ConfigUi } from "./config-registry";

/** Client-safe, fast-feedback mirrors of the API's validation. The API stays the authority. */

export const FABLE_MESSAGE = "Claude Fable models are not allowed (zero data retention).";

export const jsonValueSchema = z.json();
export type JsonValue = z.infer<typeof jsonValueSchema>;

/** Money and tolerances stay decimal strings end to end; never converted to Number. */
export const decimalString = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, "Enter an amount with up to 2 decimals.");

export const intervalSeconds = z.number("Enter a number.").int("Whole seconds only.").positive();
export const positiveInt = z.number("Enter a number.").int("Whole numbers only.").positive();
export const nonNegativeInt = z.number("Enter a number.").int("Whole numbers only.").min(0);
export const nullableDays = z.number("Enter a number.").int("Whole days only.").positive().nullable();
export const confidence = z.number("Enter a number.").min(0).max(1);

/** Compare two non-negative decimal strings with up to 2 decimals, without floating point. */
export function compareDecimal(a: string, b: string): number {
  const split = (s: string): [string, string] => {
    const [whole = "0", frac = ""] = s.trim().split(".");
    return [whole.replace(/^0+(?=\d)/, ""), frac.padEnd(2, "0").slice(0, 2)];
  };
  const [aw, af] = split(a);
  const [bw, bf] = split(b);
  const width = Math.max(aw.length, bw.length);
  // Same-width digit strings order lexicographically, so no number conversion is needed.
  const x = `${aw.padStart(width, "0")}.${af}`;
  const y = `${bw.padStart(width, "0")}.${bf}`;
  return x < y ? -1 : x > y ? 1 : 0;
}

const currencyKey = z.string().regex(/^([A-Z]{3}|\*)$/, "Use a 3-letter currency code or *.");

export const modelRoleSchema = z.object({
  model_id: z
    .string()
    .trim()
    .min(1, "Enter a model ID.")
    .refine((v) => !v.toLowerCase().includes("fable"), FABLE_MESSAGE),
  effort: z.enum(["low", "medium", "high", "max"]).nullable(),
  timeout_s: positiveInt,
});

export const tolerancesSchema = z
  .record(currencyKey, decimalString)
  .refine((v) => "*" in v, "Keep the All other currencies row.");

export const bankFeeBandsSchema = z.array(
  z
    .object({ currency: currencyKey, min_fee: decimalString, max_fee: decimalString })
    .refine((b) => compareDecimal(b.min_fee, b.max_fee) <= 0, {
      path: ["max_fee"],
      message: "Maximum fee must not be below the minimum fee.",
    }),
);

export const backoffSchema = z
  .array(z.number("Enter a number.").int("Whole seconds only.").min(0))
  .min(1, "Add at least one delay.");

export const maxAttemptsSchema = z
  .record(z.string().min(1), positiveInt)
  .refine((v) => "*" in v, "Keep the All other codes row.");

export const groupRolesSchema = z
  .array(
    z.object({
      group_name: z.string().trim().min(1, "Enter a group name."),
      role: z.enum(ROLES),
    }),
  )
  .refine((v) => v.some((m) => m.role === "ADMIN"), "At least one group must map to ADMIN.");

export const reasonSchema = z.string().trim().min(1, "Enter a reason.").max(1000);

/** The zod schema for one editor, narrowed by the row's optional range or pattern. */
export function schemaForEditor(
  editor: EditorKind,
  opts: Pick<ConfigUi, "range" | "pattern"> = {},
): z.ZodType {
  switch (editor) {
    case "number": {
      const { range } = opts;
      let n = z.number("Enter a number.");
      if (range?.integer) n = n.int("Whole numbers only.");
      if (range) n = n.min(range.min, `Must be at least ${range.min}.`);
      if (range?.max !== undefined) n = n.max(range.max, `Must be at most ${range.max}.`);
      return n;
    }
    case "nullable-days":
      return nullableDays;
    case "tolerance-table":
      return tolerancesSchema;
    case "bank-fee-bands":
      return bankFeeBandsSchema;
    case "backoff-list":
      return backoffSchema;
    case "max-attempts":
      return maxAttemptsSchema;
    case "model-role":
      return modelRoleSchema;
    case "group-roles":
      return groupRolesSchema;
    case "switch":
      return z.boolean();
    case "text":
      return opts.pattern
        ? z.string().regex(new RegExp(opts.pattern), "Use the format HH:MM.")
        : z.string();
    case "decimal-nullable":
      return decimalString.nullable();
    case "json":
      return jsonValueSchema;
  }
}
