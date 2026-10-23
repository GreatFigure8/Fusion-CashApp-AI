import { MonoLabel } from "@/components/common/mono-label";
import type { Schemas } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { buildAutofixTimeline } from "./autofix-timeline";

type Props = Readonly<{
  attempts: readonly Schemas["AutofixAttemptOut"][];
  itemState?: string | null;
}>;

/** The auto-fixes the system tried, oldest first, as a vertical timeline. */
export function AutofixList({ attempts, itemState = null }: Props): React.JSX.Element {
  const timeline = buildAutofixTimeline(attempts, itemState);
  return (
    <section className="grid gap-2" aria-labelledby="autofix-title">
      <MonoLabel as="h3">
        <span id="autofix-title">
          Auto-fixes tried · {timeline.tried} of {timeline.limit}
        </span>
      </MonoLabel>
      {timeline.steps.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          No automatic fix has been tried for this item.
        </p>
      ) : (
        <ol className="grid gap-3 border-l border-line-strong pl-1">
          {timeline.steps.map((step, index) => (
            <li key={`${step.at}-${index}`} data-step className="relative pl-6 text-[13px]">
              <span
                aria-hidden
                className={cn(
                  "absolute top-1 left-0 size-2.5 rounded-full",
                  step.tone === "err" ? "bg-err" : "bg-warn",
                )}
              />
              <p>{step.text}</p>
              <p className="text-xs text-muted-foreground">
                {step.detail}
                {step.detail && step.at ? " · " : ""}
                {step.at ? (
                  <time dateTime={step.at} className="font-mono">
                    {formatRelative(step.at)}
                  </time>
                ) : null}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
