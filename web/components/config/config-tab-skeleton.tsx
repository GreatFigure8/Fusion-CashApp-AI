import { GlassPanel, PanelBody } from "@/components/common/glass-panel";
import { SkeletonRows } from "@/components/common/skeleton-rows";

/** Loading state for a group body: one glass card of skeleton rows. */
export function ConfigTabSkeleton() {
  return (
    <GlassPanel as="section" aria-label="Loading settings">
      <PanelBody>
        <div data-testid="config-tab-skeleton" aria-busy="true">
          <SkeletonRows rows={6} height={14} caption="Reading settings…" />
        </div>
      </PanelBody>
    </GlassPanel>
  );
}
