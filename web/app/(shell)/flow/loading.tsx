import { GlassPanel } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { Skeleton } from "@/components/ui/skeleton";

export default function FlowLoading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading the flow">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-20 rounded-2xl" />
        ))}
      </div>
      <GlassPanel className="p-4">
        <SkeletonRows rows={6} height={40} caption="Reading the flow…" />
      </GlassPanel>
    </div>
  );
}
