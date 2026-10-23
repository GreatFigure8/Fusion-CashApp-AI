import type { HtmlReportKind, HtmlReportParams, HtmlSection, HtmlWindow } from "./schemas";

export const KIND_LABELS: Readonly<Record<HtmlReportKind, string>> = {
  PROGRESS_SUMMARY: "Progress summary",
  EXCEPTIONS_AGING: "Exceptions aging",
  MODEL_EFFICIENCY: "Model efficiency",
};

export const WINDOW_LABELS: Readonly<Record<HtmlWindow, string>> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  mtd: "Month to date",
};

export const SECTION_LABELS: Readonly<Record<HtmlSection, string>> = {
  HEADLINE: "Headline numbers",
  MONEY_BY_CURRENCY: "Money by currency",
  THROUGHPUT: "Throughput",
  EXCEPTIONS_BY_REASON: "Exceptions by reason",
  MODEL_EFFICIENCY: "Model efficiency",
};

/** The same-origin preview URL for a set of builder params. */
export function previewUrl(params: HtmlReportParams): string {
  const q = new URLSearchParams({ kind: params.kind, window: params.window });
  for (const s of params.sections) q.append("sections", s);
  return `/api/reports/html/preview?${q.toString()}`;
}

/** The file name from a `Content-Disposition: attachment; filename="..."` header, or null. */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const match = /filename="([^"\\/]+)"/.exec(header) ?? /filename=([^;\s]+)/.exec(header);
  return match?.[1] ?? null;
}

/** `J. Stevenson · 13:40` for today, `20 Oct` for an earlier day (UTC). */
export function whoWhen(actor: string, at: string, now: Date): string {
  const d = new Date(at);
  const sameDay = d.toISOString().slice(0, 10) === now.toISOString().slice(0, 10);
  const when = sameDay
    ? d.toISOString().slice(11, 16)
    : `${d.getUTCDate()} ${d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })}`;
  return `${actor} · ${when}`;
}
