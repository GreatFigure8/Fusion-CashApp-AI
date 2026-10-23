import { Skeleton } from "@/components/ui/skeleton";

export default function FlowLoading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading the flow">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-20 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 md:flex md:overflow-x-hidden">
        {Array.from({ length: 12 }, (_, index) => (
          <Skeleton key={index} className="h-40 md:w-44 md:shrink-0" />
        ))}
      </div>
    </div>
  );
}
