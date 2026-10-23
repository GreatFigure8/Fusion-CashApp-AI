import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api/types";

type Props = Readonly<{
  errorCode: Schemas["ErrorCode"] | null;
  summary: string | null;
  /** The reasoning recorded with the latest failure, from the item's history. */
  lastError: string | null;
}>;

export function WhyStuck({ errorCode, summary, lastError }: Props): React.JSX.Element {
  return (
    <section className="grid gap-2" aria-labelledby="why-stuck-title">
      <div className="flex items-center gap-2">
        <h3 id="why-stuck-title" className="text-sm font-medium">
          Why it&apos;s stuck
        </h3>
        {errorCode ? (
          <Badge variant="outline" className="font-mono">
            {errorCode}
          </Badge>
        ) : null}
      </div>
      <p className="text-sm">{summary ?? "No summary has been written for this item yet."}</p>
      {lastError ? (
        <p className="rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
          {lastError}
        </p>
      ) : null}
    </section>
  );
}
