import Link from "next/link";

import { Sparkline } from "@/components/flow/sparkline";
import { Pill } from "@/components/common/pill";
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
        "flex min-w-0 flex-col gap-2 rounded-xl border border-line bg-surface-2/40 px-3.5 py-3 text-sm transition-colors",
        "hover:border-brand-hi/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-hi/60",
      )}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs uppercase tracking-[0.06em]">{label}</span>
        {tile.errors > 0 ? (
          <span data-slot="error-badge" aria-label={`${tile.errors} errors`}>
            <Pill tone="err" mono>
              {tile.errors}
            </Pill>
          </span>
        ) : null}
      </span>
      <span className="flex items-baseline gap-2">
        <span className="font-mono text-2xl font-medium tabular-nums" data-slot="in-queue">
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
