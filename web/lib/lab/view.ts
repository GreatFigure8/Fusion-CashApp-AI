import type { ResultCard } from "@/components/common/llm-chat/chat-schemas";
import type { DiffLine } from "@/components/common/diff-block";
import type { PillTone } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";
import { hasPermission, type Me } from "@/lib/permissions";

import { CANDIDATE_ID, REPLAY_ID } from "./schemas";

/** Pure and client-safe: every rule here is a display rule. The API owns replay, stale and promote. */

export type LabCandidate = Schemas["CandidateOut"];
export type LabReplay = Schemas["ReplayResultOut"];
export type LabOutcome = Schemas["ReplayOutcome"];

export type LabViewState =
  | "empty"
  | "unreplayed"
  | "loading"
  | "done"
  | "stale"
  | "failed"
  | "promoted"
  | "discarded";

export function labViewState(
  candidate: LabCandidate | null,
  replay: LabReplay | null,
): LabViewState {
  if (candidate === null) return "empty";
  if (candidate.status === "PROMOTED") return "promoted";
  if (candidate.status === "DISCARDED") return "discarded";
  if (replay === null) return "unreplayed";
  if (replay.status === "RUNNING") return "loading";
  if (replay.status === "FAILED") return "failed";
  if (replay.status === "STALE" || replay.base_version !== candidate.live_version) return "stale";
  return "done";
}

/** Promote needs config write, an open candidate and a finished replay on the current live version. */
export function canPromote(me: Me, candidate: LabCandidate, replay: LabReplay | null): boolean {
  return (
    hasPermission(me, "config:write") &&
    candidate.status === "OPEN" &&
    replay !== null &&
    replay.status === "DONE" &&
    replay.base_version === candidate.live_version
  );
}

function show(value: Schemas["JsonValue"] | undefined): string {
  if (value === undefined) return "null";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** One context line with the key, then the old value in red and the new value in green. */
export function diffLines(rows: readonly Schemas["ConfigDiffRow"][]): DiffLine[] {
  return rows.flatMap((row) => [
    { op: " " as const, text: row.key },
    { op: "-" as const, text: show(row.before) },
    { op: "+" as const, text: show(row.after) },
  ]);
}

export function auditCaption(displayName: string, replayId: string, version: number): string {
  return `Records ${displayName} · replay ${replayId} · expected version ${version}`;
}

export const OUTCOME_TONE: Readonly<Record<LabOutcome, PillTone>> = {
  matched: "ok",
  ambiguous: "warn",
  no_receipt: "err",
  variance: "err",
  lines_failed: "err",
  no_input: "muted",
};

/** The lab URL for a candidate and replay, or null when an id is not in the expected shape. */
export function labHref(candidate: string, replay: string | null): string | null {
  if (!CANDIDATE_ID.test(candidate)) return null;
  if (replay === null) return `/lab?candidate=${candidate}`;
  if (!REPLAY_ID.test(replay)) return null;
  return `/lab?candidate=${candidate}&replay=${replay}`;
}

/** Where the page goes when the chat finishes a tool call: only a replay card moves it. */
export function replayCardHref(card: ResultCard): string | null {
  return card.kind === "replay_card" ? labHref(card.candidate_id, card.replay_id) : null;
}

export function csvHref(replayId: string): string | null {
  return REPLAY_ID.test(replayId) ? `/api/lab/replays/${replayId}/items.csv` : null;
}
