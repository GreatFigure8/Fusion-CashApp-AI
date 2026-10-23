import { z } from "zod";

import { yesterdayUtc } from "./format";

export const MAX_RANGE_DAYS = 366;
export const MAX_RECIPIENTS = 50;

export const isoDay = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/)
  .refine((v) => !Number.isNaN(Date.parse(`${v}T00:00:00Z`)), "Not a real date");

export const reportTab = z.enum(["daily", "partial"]);
export type ReportTab = z.infer<typeof reportTab>;

const first = (v: unknown): unknown => (Array.isArray(v) ? v[0] : v);

export type ReportsView = Readonly<{
  tab: ReportTab;
  date: string;
  from: string;
  to: string;
}>;

/** Reads the page's searchParams. A bad or missing value falls back to its default; never throws. */
export function parseReportsSearchParams(
  raw: Readonly<Record<string, string | string[] | undefined>>,
  now: Date,
): ReportsView {
  const yesterday = yesterdayUtc(now);
  const tab = reportTab.catch("daily").parse(first(raw.tab));
  const day = (v: unknown): string => isoDay.catch(yesterday).parse(first(v));
  const date = day(raw.date);
  let from = day(raw.from);
  let to = day(raw.to);
  const span = (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000;
  if (span < 0 || span + 1 > MAX_RANGE_DAYS) {
    from = yesterday;
    to = yesterday;
  }
  return { tab, date, from, to };
}

export const generateInput = z.object({ date: isoDay });
export type GenerateInput = z.infer<typeof generateInput>;

export const emailInput = z.object({
  date: isoDay,
  recipients: z.array(z.email()).min(1).max(MAX_RECIPIENTS).optional(),
});
export type EmailInput = z.infer<typeof emailInput>;

export const exportParams = z.object({
  report: z.enum(["daily-summary", "partially-paid"]),
  format: z.enum(["csv", "xlsx"]),
  date: isoDay.optional(),
  from: isoDay.optional(),
  to: isoDay.optional(),
});
export type ExportParams = z.infer<typeof exportParams>;

/** Splits a free-text recipient box on commas, semicolons, spaces and newlines. */
export function splitRecipients(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}
