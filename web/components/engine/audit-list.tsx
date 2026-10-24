import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import type { Schemas } from "@/lib/api/types";
import { formatLockTime } from "@/lib/lock-time";

const ACTION_TEXT: Readonly<Record<Schemas["EngineAuditOut"]["action"], string>> = {
  PAUSE: "paused",
  RESUME: "resumed",
  DRAIN: "drained",
  THROTTLE: "changed the throttle for",
  REPLAY: "replayed dead letters for",
};

export function AuditList({ rows }: Readonly<{ rows: readonly Schemas["EngineAuditOut"][] }>) {
  return (
    <GlassPanel as="section" aria-label="Audit">
      <PanelHeader title="Audit">
        <MonoLabel>who · when · why</MonoLabel>
      </PanelHeader>
      <PanelBody>
        {rows.length === 0 ? (
          <p className="text-sm text-soft">No engine changes recorded yet.</p>
        ) : (
          <ul className="grid gap-2.5">
            {rows.map((r) => (
              <li key={r.id} className="grid grid-cols-[44px_1fr] gap-x-2 text-sm">
                <time dateTime={r.at} className="font-mono text-xs text-faint">
                  {formatLockTime(r.at)}
                </time>
                <div>
                  <span className="font-medium">{r.actor_name}</span>{" "}
                  <span>
                    {ACTION_TEXT[r.action]} {r.stations.join(", ")}
                  </span>
                  <p className="text-soft">“{r.reason}”</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </PanelBody>
    </GlassPanel>
  );
}
