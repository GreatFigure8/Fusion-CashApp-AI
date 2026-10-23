import { z } from "zod";

import type { Schemas } from "@/lib/api/types";

/**
 * Zod schemas for the two `/flow/stream` events. Each is typed against the generated OpenAPI
 * type, so a field added to or dropped from the API fails `tsc` here instead of in the browser.
 */

const lockSchema = z.object({
  item_id: z.number(),
  owner: z.string(),
  owner_name: z.string(),
  acquired_at: z.string(),
  expires_at: z.string(),
}) satisfies z.ZodType<Schemas["LockInfoOut"]>;

const tileSchema = z.object({
  stage: z.enum([
    "INTAKE",
    "CLASSIFY",
    "EXTRACT",
    "ADJUDICATE",
    "VALIDATE",
    "RESOLVE_CUSTOMER",
    "FAST_PATH",
    "MATCH_RECEIPT",
    "AWAITING_RECEIPT",
    "MATCH_LINES",
    "APPLY",
    "WRITE_BACK",
    "DONE",
  ]),
  in_queue: z.number(),
  in_progress: z.number(),
  errors: z.number(),
  throughput_per_min: z.array(z.number()),
  p95_dwell_s: z.number().nullable(),
  awaiting_buckets: z
    .object({
      "0-2d": z.number(),
      "3-7d": z.number(),
      "8-30d": z.number(),
      ">30d": z.number(),
    })
    .nullable(),
}) satisfies z.ZodType<Schemas["FlowTileOut"]>;

export const flowSummarySchema: z.ZodType<Schemas["FlowSummaryOut"]> = z.object({
  kpis: z.object({
    in_today: z.number(),
    auto_applied_pct: z.number().nullable(),
    applied_by_currency: z.array(z.object({ currency: z.string(), amount: z.string() })),
    needs_person: z.number(),
  }),
  stages: z.array(tileSchema),
  pollers: z.array(z.object({ name: z.string(), last_cycle_at: z.string().nullable() })),
  cohere_utilisation_pct: z.number().nullable(),
  backlog: z.array(
    z.object({
      id: z.number(),
      name: z.string(),
      processed: z.number(),
      total: z.number(),
      eta_minutes: z.number().nullable(),
      status: z.string(),
    }),
  ),
  generated_at: z.string(),
});

export const itemChangedSchema: z.ZodType<Schemas["ItemChangedOut"]> = z.object({
  id: z.number(),
  stage: z.enum([
    "INTAKE",
    "CLASSIFY",
    "EXTRACT",
    "ADJUDICATE",
    "VALIDATE",
    "RESOLVE_CUSTOMER",
    "FAST_PATH",
    "MATCH_RECEIPT",
    "MATCH_LINES",
    "APPLY",
    "WRITE_BACK",
    "DONE",
  ]),
  state: z.enum(["PENDING", "IN_PROGRESS", "AWAITING_RECEIPT", "ESCALATED", "DONE", "ARCHIVED"]),
  lock: lockSchema.nullable(),
  payment_status: z
    .enum([
      "payment-success",
      "payment-less-than-total-due-success",
      "payment-more-than-total-due-success",
      "payment-previously-applied",
      "invoice-not-found",
      "customer-not-found",
      "missing-payment-date",
      "receipt-not-found",
      "zero-amount",
      "payment-apply-failed-system",
      "payment-apply-failed-receipt-closed",
      "payment-apply-failed-zero-balance",
    ])
    .nullable(),
  updated_at: z.string(),
});

/** The data payload of any `/flow/stream` event; the event name says which one. */
export const flowStreamDataSchema = z.union([flowSummarySchema, itemChangedSchema]);
export type FlowStreamData = z.infer<typeof flowStreamDataSchema>;
