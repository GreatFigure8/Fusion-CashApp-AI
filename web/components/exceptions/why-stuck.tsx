import type { ReactNode } from "react";

import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";

import { REASON_TONE } from "./reason";

type Props = Readonly<{
  errorCode: Schemas["ErrorCode"] | null;
  summary: string | null;
  /** The reasoning recorded with the latest failure, from the item's history. */
  lastError: string | null;
  /** Candidate receipt tiles, streamed in by the page. */
  candidates?: ReactNode;
}>;

export function WhyStuck({ errorCode, summary, lastError, candidates }: Props): React.JSX.Element {
  return (
    <section className="grid gap-2" aria-labelledby="why-stuck-title">
      <div className="flex items-center gap-2">
        <MonoLabel as="h3">
          <span id="why-stuck-title">Why it&apos;s stuck</span>
        </MonoLabel>
        {errorCode ? (
          <Pill tone={REASON_TONE[errorCode]} mono>
            {errorCode}
          </Pill>
        ) : null}
      </div>
      <p className="text-[13.5px]">{summary ?? "No summary has been written for this item yet."}</p>
      {candidates}
      {lastError ? (
        <p className="rounded-xl bg-surface-3 px-3 py-2 font-mono text-xs text-muted-foreground">
          {lastError}
        </p>
      ) : null}
    </section>
  );
}
