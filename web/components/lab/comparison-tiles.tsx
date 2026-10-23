import { KpiCard } from "@/components/common/kpi-card";
import type { LabReplay } from "@/lib/lab/view";

/** Four counts of how the replay differs from live. */
export function ComparisonTiles({ replay }: { replay: LabReplay }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
      <KpiCard label="Match differently" value={replay.changed} size="sm" />
      <KpiCard label="Newly matched" value={`+${replay.newly_matched}`} tone="ok" size="sm" />
      <KpiCard label="Newly failed" value={`+${replay.newly_failed}`} tone="err" size="sm" />
      <KpiCard label="Newly ambiguous" value={replay.newly_ambiguous} tone="warn" size="sm" />
    </div>
  );
}
