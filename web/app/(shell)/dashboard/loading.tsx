import { KpiCard } from "@/components/common/kpi-card";
import { SkeletonRows } from "@/components/common/skeleton-rows";

export default function Loading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading progress">
      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
        {["Receipts matched", "Automation", "Awaiting receipt", "Open exceptions"].map((label) => (
          <KpiCard key={label} label={label} value={null} loading />
        ))}
      </div>
      <SkeletonRows rows={6} height={16} caption="Reading aggregates…" />
    </div>
  );
}
