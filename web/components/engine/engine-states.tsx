import { ActionButton } from "@/components/common/action-button";
import { GlassPanel, PanelBody } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { StateCard } from "@/components/common/state-card";

export function BusUnavailable({ onRetry }: Readonly<{ onRetry: () => void }>) {
  return (
    <StateCard
      kind="error"
      label="Error · bus"
      headline="Bus health unavailable"
      body="Controls are disabled until lag can be read."
      actions={
        <ActionButton variant="outline" onClick={onRetry}>
          Retry
        </ActionButton>
      }
    />
  );
}

export function OperatorBanner() {
  return (
    <GlassPanel as="div" tone="warn">
      <PanelBody className="flex items-center gap-3 text-sm">
        <MonoLabel>Operator view</MonoLabel>
        <span>
          <strong className="font-medium">Read-only</strong> · Pause, drain, throttle and replay need
          admin.
        </span>
      </PanelBody>
    </GlassPanel>
  );
}
