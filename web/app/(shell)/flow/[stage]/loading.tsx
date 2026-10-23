import { GlassPanel } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";

export default function StageLoading() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading items">
      <GlassPanel className="p-4">
        <SkeletonRows rows={10} height={28} caption="Reading items…" />
      </GlassPanel>
    </div>
  );
}
