import { SkeletonRows } from "@/components/common/skeleton-rows";
import { StateCard } from "@/components/common/state-card";

export default function Loading() {
  return (
    <div className="grid gap-4 p-4">
      <StateCard kind="loading" headline="Reading consumer lag…">
        <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(210px,1fr))]">
          {Array.from({ length: 12 }, (_, i) => (
            <li key={i}>
              <SkeletonRows rows={3} />
            </li>
          ))}
        </ul>
      </StateCard>
    </div>
  );
}
