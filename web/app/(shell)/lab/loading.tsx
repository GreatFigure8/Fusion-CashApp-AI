import { GlassPanel, PanelBody } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";

export default function LabLoading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading the lab">
      <GlassPanel>
        <PanelBody>
          <SkeletonRows rows={1} height={28} caption="Loading the lab" />
        </PanelBody>
      </GlassPanel>
      <div className="flex flex-wrap gap-4">
        <GlassPanel solid className="min-w-0 flex-[1_1_380px]">
          <PanelBody>
            <SkeletonRows rows={8} />
          </PanelBody>
        </GlassPanel>
        <GlassPanel className="min-w-0 flex-[999_1_520px]">
          <PanelBody>
            <SkeletonRows rows={6} height={22} />
          </PanelBody>
        </GlassPanel>
      </div>
    </div>
  );
}
