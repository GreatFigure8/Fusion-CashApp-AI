import { GlassPanel } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { Skeleton } from "@/components/ui/skeleton";

export default function ExceptionsLoading() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading exceptions">
      <Skeleton className="h-14 w-full rounded-2xl" />
      <div className="flex flex-wrap gap-2">
        {Array.from({ length: 7 }, (_, i) => (
          <Skeleton key={i} className="h-8 w-32 rounded-full" />
        ))}
      </div>
      <GlassPanel className="p-4">
        <SkeletonRows rows={10} height={32} caption="Reading exceptions…" />
      </GlassPanel>
    </div>
  );
}
