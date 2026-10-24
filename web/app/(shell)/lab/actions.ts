"use server";

import { refresh } from "next/cache";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import { apiError } from "@/lib/api/errors";
import { getSession } from "@/lib/auth/session";
import { discardInput, promoteInput, replayAgainInput } from "@/lib/lab/schemas";
import { err } from "@/lib/result";

const SESSION_EXPIRED = () =>
  err(apiError(401, "session_expired", "Your session has expired. Sign in again.", null));

/** Start a replay of the candidate over the window. The API enforces `lab:run`. */
export const replayAgainAction = apiAction(replayAgainInput, async ({ candidateId, windowDays }) => {
  if ((await getSession()) === null) return SESSION_EXPIRED();
  const result = await api("post", "/lab/candidates/{candidate_id}/replays", {
    params: { candidate_id: candidateId },
    body: { window_days: windowDays },
  });
  if (result.ok) refresh();
  return result;
});

/** Promote the candidate to live: the same audited config write as Settings. */
export const promoteAction = apiAction(
  promoteInput,
  async ({ candidateId, replayId, reason, expectedVersion }) => {
    if ((await getSession()) === null) return SESSION_EXPIRED();
    const result = await api("post", "/lab/candidates/{candidate_id}/promote", {
      params: { candidate_id: candidateId },
      body: { replay_id: replayId, reason, expected_version: expectedVersion },
    });
    if (result.ok) refresh();
    return result;
  },
);

export const discardAction = apiAction(discardInput, async ({ candidateId, reason }) => {
  if ((await getSession()) === null) return SESSION_EXPIRED();
  const result = await api("post", "/lab/candidates/{candidate_id}/discard", {
    params: { candidate_id: candidateId },
    body: { reason: reason ?? null },
  });
  if (result.ok) refresh();
  return result;
});

/** Open candidates for the nav count: `open_count` of a one-row list. */
export const labOpenCountAction = apiAction(async () => {
  if ((await getSession()) === null) return SESSION_EXPIRED();
  const result = await api("get", "/lab/candidates", { query: { limit: 1 } });
  return result.ok ? { ok: true as const, value: result.value.open_count } : result;
});
