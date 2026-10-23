import Link from "next/link";

import { Sparkline } from "@/components/flow/sparkline";
import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api/types";
import { formatDuration, humanizeEnum } from "@/lib/format";
import { cn } from "@/lib/utils";

const BUCKET_ORDER = ["0-2d", "3-7d", "8-30d", ">30d"] as const;

/** One station of the assembly line; a link to its item table. */
export function StageTile({
  tile,
  cohereUtilisationPct,
}: {
  tile: Schemas["FlowTileOut"];
  cohereUtilisationPct: number | null;
}) {
  const label = humanizeEnum(tile.stage);
  return (
    <Link
      href={`/flow/${tile.stage.toLowerCase()}`}
      data-stage={tile.stage}
      className={cn(
        "flex min-w-0 flex-col gap-1.5 rounded-lg border bg-card p-3 text-sm transition-colors",
        "hover:border-ring focus-visible:ring-2 focus-visible:ring-ring",
        "md:w-44 md:shrink-0",
      )}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="font-medium">{label}</span>
        {tile.errors > 0 ? (
          <Badge variant="destructive" data-slot="error-badge" aria-label={`${tile.errors} errors`}>
            {tile.errors}
          </Badge>
        ) : null}
      </span>
      <span className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums" data-slot="in-queue">
          {tile.in_queue}
        </span>
        <span className="text-xs text-muted-foreground">
          {tile.stage === "AWAITING_RECEIPT" ? "waiting" : "queued"}
        </span>
      </span>
      {tile.stage !== "AWAITING_RECEIPT" && tile.stage !== "DONE" ? (
        <span className="text-xs text-muted-foreground tabular-nums">
          {tile.in_progress} in progress
        </span>
      ) : null}
      <Sparkline values={tile.throughput_per_min} />
      {tile.stage !== "AWAITING_RECEIPT" && tile.stage !== "DONE" ? (
        <span className="text-xs text-muted-foreground">
          p95 dwell {formatDuration(tile.p95_dwell_s)}
        </span>
      ) : null}
      {tile.awaiting_buckets ? (
        <dl className="grid grid-cols-2 gap-x-2 text-xs text-muted-foreground">
          {BUCKET_ORDER.map((bucket) => (
            <div key={bucket} className="flex justify-between gap-1">
              <dt>{bucket}</dt>
              <dd className="tabular-nums text-foreground">{tile.awaiting_buckets?.[bucket] ?? 0}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {tile.stage === "EXTRACT" && cohereUtilisationPct !== null ? (
        <span className="text-xs text-muted-foreground">Cohere {Math.round(cohereUtilisationPct)}%</span>
      ) : null}
    </Link>
  );
}
