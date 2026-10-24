import { GlassPanel, PanelBody } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";

export default function ReviewLoading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading review">
      <GlassPanel>
        <PanelBody>
          <SkeletonRows rows={4} caption="Loading review" />
        </PanelBody>
      </GlassPanel>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,400px),1fr))] gap-4">
        <GlassPanel>
          <PanelBody>
            <SkeletonRows rows={5} />
          </PanelBody>
        </GlassPanel>
        <GlassPanel>
          <PanelBody>
            <SkeletonRows rows={5} />
          </PanelBody>
        </GlassPanel>
      </div>
    </div>
  );
}
