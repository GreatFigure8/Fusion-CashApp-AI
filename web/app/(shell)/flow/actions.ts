"use server";

import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import { apiError } from "@/lib/api/errors";
import { getSession } from "@/lib/auth/session";
import { err, ok } from "@/lib/result";

async function authenticated() {
  // Checked here as well as in proxy.ts: the API is the control, this is the early exit.
  return (await getSession()) !== null;
}

const SESSION_EXPIRED = () =>
  err(apiError(401, "session_expired", "Your session has expired. Sign in again.", null));

/** Re-reads the summary for the Retry button when the live stream has not delivered one. */
export const refreshFlowSummary = apiAction(async () => {
  if (!(await authenticated())) return SESSION_EXPIRED();
  return api("get", "/flow/summary");
});

const pauseSchema = z.number().int().positive();

/** Pause a running backlog batch. The API enforces `backlog:run`. */
export const pauseBacklogBatch = apiAction(pauseSchema, async (id) => {
  if (!(await authenticated())) return SESSION_EXPIRED();
  const result = await api("post", "/backlog/batches/{id}/pause", { params: { id } });
  return result.ok ? ok(undefined) : result;
});
