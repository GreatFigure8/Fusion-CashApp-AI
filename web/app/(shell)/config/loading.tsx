import { ConfigTabSkeleton } from "@/components/config/config-tab-skeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-7 w-48" />
      <div className="flex flex-col gap-4 lg:flex-row">
        <Skeleton className="h-12 w-full lg:h-72 lg:w-52 lg:shrink-0" />
        <div className="min-w-0 flex-1">
          <ConfigTabSkeleton tab="access" />
        </div>
      </div>
    </div>
  );
}
