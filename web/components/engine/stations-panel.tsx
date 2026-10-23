import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { stateCounts, type Station } from "@/lib/engine/view";

import { StationCard } from "./station-card";

export function StationsPanel({
  stations,
  enabled,
  canControl,
  onAction,
}: Readonly<{
  stations: readonly Station[];
  enabled: boolean;
  canControl: boolean;
  onAction: (kind: "pause" | "resume" | "drain", station: string) => void;
}>) {
  const counts = stateCounts(stations);
  return (
    <GlassPanel as="section" aria-label="Stations">
      <PanelHeader title="Stations">
        <Pill tone="ok">{counts.running} running</Pill>
        <Pill tone="warn">{counts.paused} paused</Pill>
        <Pill tone="accent">{counts.draining} draining</Pill>
      </PanelHeader>
      <PanelBody>
        <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(210px,1fr))]">
          {stations.map((s) => (
            <StationCard
              key={s.name}
              station={s}
              enabled={enabled}
              canControl={canControl}
              onPause={(n) => onAction("pause", n)}
              onResume={(n) => onAction("resume", n)}
              onDrain={(n) => onAction("drain", n)}
            />
          ))}
        </ul>
      </PanelBody>
    </GlassPanel>
  );
}
