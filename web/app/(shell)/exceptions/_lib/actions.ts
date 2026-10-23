"use server";

import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/types";

const itemId = z.number().int().positive();
const text = z.string().trim().min(1).max(2000);

export const dequeueAction = apiAction(z.object({ itemId }), ({ itemId: id }) =>
  api("post", "/items/{item_id}/lock", { params: { item_id: id } }),
);

export const renewLockAction = apiAction(z.object({ itemId }), ({ itemId: id }) =>
  api("post", "/items/{item_id}/lock/renew", { params: { item_id: id } }),
);

export const releaseLockAction = apiAction(z.object({ itemId }), ({ itemId: id }) =>
  api("delete", "/items/{item_id}/lock", { params: { item_id: id } }),
);

// The API validates the corrected extraction (the single source of the extraction rules); the
// action checks only the envelope, so the extraction schema is never re-declared in the web.
const requeueInput = z.object({
  itemId,
  body: z.custom<Schemas["RequeueIn"]>(
    (value) =>
      typeof value === "object" &&
      value !== null &&
      typeof (value as { note?: unknown }).note === "string",
  ),
});

export const requeueAction = apiAction(requeueInput, ({ itemId: id, body }) =>
  api("post", "/items/{item_id}/requeue", { params: { item_id: id }, body }),
);

export const reverseAction = apiAction(
  z.object({
    itemId,
    ledgerId: z.number().int().positive(),
    reason: text,
    confirmReceiptNumber: z.string().trim().min(1).max(100),
  }),
  ({ itemId: id, ledgerId, reason, confirmReceiptNumber }) =>
    api("post", "/items/{item_id}/applications/{ledger_id}/reverse", {
      params: { item_id: id, ledger_id: ledgerId },
      body: { reason, confirm_receipt_number: confirmReceiptNumber },
    }),
);

export const overrideClassificationAction = apiAction(
  z.object({ itemId, reason: text }),
  ({ itemId: id, reason }) =>
    api("post", "/items/{item_id}/classification/override", {
      params: { item_id: id },
      body: { is_remittance: true, reason },
    }),
);
