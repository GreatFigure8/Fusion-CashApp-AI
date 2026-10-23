import { Skeleton } from "@/components/ui/skeleton";

export default function ItemLoading() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading the item">
      <Skeleton className="h-20 w-full rounded-lg" />
      <div className="grid gap-3 lg:grid-cols-[2fr_3fr_minmax(320px,1.4fr)]">
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
      </div>
    </div>
  );
}
