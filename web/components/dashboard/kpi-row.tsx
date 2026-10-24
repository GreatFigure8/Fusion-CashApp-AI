import { KpiCard } from "@/components/common/kpi-card";
import type { Schemas } from "@/lib/api/types";
import { formatAge, formatPct } from "@/lib/metrics/format";

type Summary = Schemas["ProgressSummary"];

/** The four headline tiles. Each label states its window, or "now" for a current-state count. */
export function KpiRow({
  summary,
  window,
  stale = false,
}: {
  summary: Summary;
  window: string;
  stale?: boolean;
}) {
  const { awaiting_receipt: awaiting, open_exceptions: open } = summary;
  return (
    <div
      data-slot="kpi-row"
      data-stale={stale ? "true" : undefined}
      className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]"
    >
      <KpiCard
        label={`Receipts matched · ${window}`}
        value={<span className="font-mono text-[30px]">{summary.receipts_matched}</span>}
        hint="Reserved and at least one line applied"
      />
      <KpiCard
        label={`Automation · ${window}`}
        variant="ring"
        progress={summary.automation_rate ?? 0}
        value={<span className="font-mono">{formatPct(summary.automation_rate, 0)}</span>}
        hint={
          summary.automation_rate === null
            ? "Nothing completed in this window"
            : `no human touch · n ${summary.done_items}`
        }
      />
      <KpiCard
        label="Awaiting receipt · now"
        tone="accent"
        value={<span className="font-mono text-[30px]">{awaiting.count}</span>}
        hint={formatAge(awaiting.oldest_age_days, awaiting.aging_limit_days)}
      />
      <KpiCard
        label="Open exceptions · now"
        tone="warn"
        value={<span className="font-mono text-[30px]">{open.total}</span>}
        hint={`${open.locked} locked · ${open.dead_lettered} dead-lettered`}
      />
    </div>
  );
}
