import { GlassPanel } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { Skeleton } from "@/components/ui/skeleton";

export default function ItemLoading() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading the item">
      <Skeleton className="h-20 w-full rounded-2xl" />
      <div className="grid gap-3 lg:grid-cols-[2fr_3fr_minmax(320px,1.4fr)]">
        {Array.from({ length: 3 }, (_, index) => (
          <GlassPanel key={index} className="p-4">
            <SkeletonRows rows={8} height={24} caption={index === 0 ? "Reading the item…" : undefined} />
          </GlassPanel>
        ))}
      </div>
    </div>
  );
}
