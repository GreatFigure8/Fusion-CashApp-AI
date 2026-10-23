import { Skeleton } from "@/components/ui/skeleton";

export default function ExceptionsLoading() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading exceptions">
      <Skeleton className="h-7 w-40" />
      <div className="flex flex-wrap gap-3">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-8 w-52" />
        <Skeleton className="h-8 w-44" />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-8 w-44" />
      </div>
      <div className="grid gap-1">
        <Skeleton className="h-9 w-full" />
        {Array.from({ length: 10 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    </div>
  );
}
