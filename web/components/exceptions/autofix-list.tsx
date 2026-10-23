import {
  ArrowUpCircle,
  Circle,
  Clock,
  CornerUpRight,
  Minus,
  RotateCw,
  type LucideIcon,
} from "lucide-react";

import type { Schemas } from "@/lib/api/types";

const DECISION_ICONS: Readonly<Record<string, { icon: LucideIcon; label: string }>> = {
  retry: { icon: RotateCw, label: "Retried" },
  reroute: { icon: CornerUpRight, label: "Rerouted" },
  park: { icon: Clock, label: "Parked" },
  escalate: { icon: ArrowUpCircle, label: "Escalated" },
  noop: { icon: Minus, label: "No action" },
  noop_locked: { icon: Minus, label: "Skipped (locked)" },
};

type Props = Readonly<{ attempts: readonly Schemas["AutofixAttemptOut"][] }>;

/** The auto-fixes the system tried, oldest first, each with its reasoning. */
export function AutofixList({ attempts }: Props): React.JSX.Element {
  return (
    <section className="grid gap-2" aria-labelledby="autofix-title">
      <h3 id="autofix-title" className="text-sm font-medium">
        Auto-fixes tried
      </h3>
      {attempts.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No automatic fix has been tried for this item.
        </p>
      ) : (
        <ol className="grid gap-3">
          {attempts.map((attempt, index) => {
            const meta = (attempt.decision ? DECISION_ICONS[attempt.decision] : undefined) ?? {
              icon: Circle,
              label: attempt.decision ?? "Attempted",
            };
            const Icon = meta.icon;
            return (
              <li key={`${attempt.at}-${index}`} className="flex gap-3 text-sm">
                <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="grid gap-0.5">
                  <p className="flex flex-wrap items-center gap-x-2">
                    <span className="font-medium">{meta.label}</span>
                    {attempt.code ? (
                      <span className="font-mono text-xs text-muted-foreground">
                        {attempt.code}
                      </span>
                    ) : null}
                    {attempt.attempt !== null && attempt.limit !== null ? (
                      <span className="text-xs text-muted-foreground">
                        attempt {attempt.attempt} / {attempt.limit}
                      </span>
                    ) : null}
                  </p>
                  {attempt.reasoning ? (
                    <p className="text-muted-foreground">{attempt.reasoning}</p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
