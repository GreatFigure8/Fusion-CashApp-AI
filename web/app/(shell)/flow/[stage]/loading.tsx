import { Skeleton } from "@/components/ui/skeleton";

export default function StageLoading() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading items">
      <Skeleton className="h-6 w-40" />
      <div className="rounded-lg border bg-card">
        {Array.from({ length: 10 }, (_, index) => (
          <div key={index} className="flex gap-4 border-b p-2.5 last:border-b-0">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 w-24" />
          </div>
        ))}
      </div>
    </div>
  );
}
