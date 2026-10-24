import type { Schemas } from "@/lib/api/types";

/** Pure: turns auto-fix attempts into the vertical timeline the detail panel draws. */

export type TimelineStep = Readonly<{
  text: string;
  detail: string;
  at: string;
  tone: "warn" | "err";
}>;

export type AutofixTimeline = Readonly<{
  tried: number;
  limit: number;
  steps: readonly TimelineStep[];
}>;

const DECISION_TEXT: Readonly<Record<string, string>> = {
  retry: "Retried",
  reroute: "Rerouted",
  park: "Parked",
  escalate: "Escalated",
  noop: "No action",
  noop_locked: "Skipped (locked)",
};

function stepText(a: Schemas["AutofixAttemptOut"]): string {
  const label = DECISION_TEXT[a.decision ?? ""] ?? a.decision ?? "Attempted";
  return a.code ? `${label} · ${a.code}` : label;
}

export function buildAutofixTimeline(
  attempts: readonly Schemas["AutofixAttemptOut"][],
  itemState: string | null | undefined,
): AutofixTimeline {
  const steps: TimelineStep[] = attempts.map((a) => ({
    text: stepText(a),
    detail: a.reasoning ?? "",
    at: a.at,
    tone: "warn",
  }));
  if (itemState === "ESCALATED") {
    const lastEscalate = [...attempts].reverse().find((a) => a.decision === "escalate");
    steps.push({
      text: "Escalated to a person",
      detail: "Handlers exhausted",
      at: lastEscalate?.at ?? attempts[attempts.length - 1]?.at ?? "",
      tone: "err",
    });
  }
  const tried = attempts.length;
  const limit = attempts.reduce((max, a) => Math.max(max, a.limit ?? 0), 0) || tried;
  return { tried, limit, steps };
}
