import { SkeletonRows } from "@/components/common/skeleton-rows";
import { StateCard } from "@/components/common/state-card";

export default function Loading() {
  return (
    <StateCard kind="loading" label="Loading · reports" headline="Loading the report builder">
      <SkeletonRows rows={3} />
    </StateCard>
  );
}
