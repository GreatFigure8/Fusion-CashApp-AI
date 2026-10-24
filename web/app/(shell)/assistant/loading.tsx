import { Skeleton } from "@/components/ui/skeleton";

export default function AssistantLoading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading the assistant">
      <Skeleton className="h-10 w-full" />
      <div className="mx-auto flex w-full max-w-[880px] flex-col gap-4">
        <Skeleton className="ml-auto h-12 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-14 w-full rounded-2xl" />
      </div>
    </div>
  );
}
