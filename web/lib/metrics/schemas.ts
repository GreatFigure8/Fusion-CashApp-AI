import { z } from "zod";

import type { Schemas } from "@/lib/api/types";

/** The windows the dashboard offers. The API also knows `mtd`, which only the reports use. */
export const UI_WINDOWS = ["24h", "7d", "30d"] as const;
export const MetricsWindowSchema = z.enum(UI_WINDOWS);
export type DashboardWindow = z.infer<typeof MetricsWindowSchema>;
export const DEFAULT_WINDOW: DashboardWindow = "7d";

/** `?window=` from the URL; anything else falls back to the default. */
export const DashboardSearchParams = z.object({
  window: MetricsWindowSchema.catch(DEFAULT_WINDOW).default(DEFAULT_WINDOW),
});

export function parseDashboardWindow(raw: Record<string, string | string[] | undefined>) {
  const value = raw.window;
  return DashboardSearchParams.parse({ window: Array.isArray(value) ? value[0] : value }).window;
}

const awaitingSchema = z.object({
  count: z.number(),
  oldest_age_days: z.number().nullable(),
  aging_limit_days: z.number(),
});

const exceptionsSchema = z.object({
  total: z.number(),
  locked: z.number(),
  dead_lettered: z.number(),
});

const summarySchema = z.object({
  window: z.enum(["24h", "7d", "30d", "mtd"]),
  start: z.string(),
  end: z.string(),
  receipts_matched: z.number(),
  done_items: z.number(),
  automation_rate: z.number().nullable(),
  awaiting_receipt: awaitingSchema,
  open_exceptions: exceptionsSchema,
  autofix_rate: z.number().nullable(),
  human_correction_rate: z.number().nullable(),
});

export const SummaryFrameSchema = z.object({
  window: z.enum(["24h", "7d", "30d", "mtd"]),
  as_of: z.string(),
  data: summarySchema,
}) satisfies z.ZodType<Schemas["MetricsSummaryFrame"]>;

export const ActivityFrameSchema = z.object({
  id: z.number(),
  at: z.string(),
  kind: z.enum(["APPLIED", "RECEIPT_ARRIVED", "AUTOFIX", "ESCALATED"]),
  item_id: z.number().nullable(),
  text: z.string(),
}) satisfies z.ZodType<Schemas["ActivityEvent"]>;

/** Either `/metrics/stream` data frame; the SSE event name tells them apart. */
export const MetricsFrameSchema = z.union([SummaryFrameSchema, ActivityFrameSchema]);
export type MetricsFrame = z.infer<typeof MetricsFrameSchema>;
