import { z } from "zod";

/** Pure and client-safe. The URL carries the selected candidate and replay; bad ids are ignored. */

export const CANDIDATE_ID = /^p_\d+$/;
export const REPLAY_ID = /^rp_\d+$/;

const first = (value: unknown): unknown => (Array.isArray(value) ? value[0] : value);

export const labSearchParams = z.object({
  candidate: z.preprocess(first, z.string().regex(CANDIDATE_ID).optional().catch(undefined)),
  replay: z.preprocess(first, z.string().regex(REPLAY_ID).optional().catch(undefined)),
});
export type LabSearch = z.infer<typeof labSearchParams>;

export function parseLabSearch(sp: Record<string, string | string[] | undefined>): LabSearch {
  return labSearchParams.parse(sp);
}

export const candidateId = z.string().regex(CANDIDATE_ID);
export const replayId = z.string().regex(REPLAY_ID);

export const WINDOW_DAYS_DEFAULT = 30;

/** The reason is required and bounded; the API enforces the same. */
export const reasonText = z.string().trim().min(1, "A reason is required.").max(500);

export const replayAgainInput = z.object({
  candidateId,
  windowDays: z.number().int().min(1).max(90).default(WINDOW_DAYS_DEFAULT),
});

export const promoteInput = z.object({
  candidateId,
  replayId,
  reason: reasonText,
  expectedVersion: z.number().int().min(0),
});

export const discardInput = z.object({ candidateId, reason: reasonText.optional() });

/** A frame of `/lab/replays/{id}/stream` (`progress`, `done`, `failed`); anything else is dropped. */
export const replayProgressEvent = z.object({
  replay_id: z.string(),
  status: z.enum(["RUNNING", "DONE", "FAILED", "STALE"]).optional(),
  done: z.number().nullish(),
  total: z.number().nullish(),
  message: z.string().nullish(),
});
export type ReplayProgressEvent = z.infer<typeof replayProgressEvent>;
