"use server";

import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import { apiError } from "@/lib/api/errors";
import { getSession } from "@/lib/auth/session";
import { err } from "@/lib/result";

const SESSION_EXPIRED = () =>
  err(apiError(401, "session_expired", "Your session has expired. Sign in again.", null));

const MAX_QUEUE_PAGE = 50;

/** The first page of the Review queue, newest first. The API enforces `items:read`. */
export const refreshReviewQueue = apiAction(async () => {
  if ((await getSession()) === null) return SESSION_EXPIRED();
  return api("get", "/review/queue", { query: { offset: 0, limit: MAX_QUEUE_PAGE } });
});

/** Today's upload count against the limit. */
export const refreshReviewQuota = apiAction(async () => {
  if ((await getSession()) === null) return SESSION_EXPIRED();
  return api("get", "/review/quota");
});

const itemSchema = z.number().int().positive();

/** The in-depth review result for one uploaded item. */
export const loadReviewResult = apiAction(itemSchema, async (itemId) => {
  if ((await getSession()) === null) return SESSION_EXPIRED();
  return api("get", "/review/items/{item_id}/result", { params: { item_id: itemId } });
});
