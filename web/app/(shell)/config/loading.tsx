import { GlassPanel, PanelBody } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { StateCard } from "@/components/common/state-card";
import { ConfigTabSkeleton } from "@/components/config/config-tab-skeleton";
import { TopBar } from "@/components/shell/top-bar";

export default function Loading() {
  return (
    <div className="space-y-4">
      <TopBar title="Settings" search={false} />
      <StateCard kind="loading" headline="Reading settings…" />
      <div className="flex flex-col gap-4 lg:flex-row">
        <GlassPanel as="nav" aria-label="Loading groups" className="lg:w-60 lg:shrink-0 lg:self-start">
          <PanelBody>
            <SkeletonRows rows={8} />
          </PanelBody>
        </GlassPanel>
        <div className="min-w-0 flex-1">
          <ConfigTabSkeleton />
        </div>
      </div>
    </div>
  );
}
