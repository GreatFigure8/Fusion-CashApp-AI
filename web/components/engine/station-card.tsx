import { ActionButton } from "@/components/common/action-button";
import { Meter } from "@/components/common/meter";
import { Pill } from "@/components/common/pill";
import {
  canDrain,
  inFlightLabel,
  isSaturated,
  primaryControl,
  stateLabel,
  stateTone,
  type Station,
} from "@/lib/engine/view";
import { cn } from "@/lib/utils";

export function StationCard({
  station,
  enabled,
  canControl,
  onPause,
  onResume,
  onDrain,
}: Readonly<{
  station: Station;
  enabled: boolean;
  canControl: boolean;
  onPause: (name: string) => void;
  onResume: (name: string) => void;
  onDrain: (name: string) => void;
}>) {
  const paused = station.state === "PAUSED" || station.state === "DRAINED";
  const primary = primaryControl(station.state);
  const suffix = canControl ? "" : " · needs admin";
  const lag = station.lag === null ? "n/a" : String(station.lag);

  return (
    <li
      className={cn(
        "rounded-xl border border-line bg-white/[0.02] px-3.5 py-3",
        paused && "border-warn/40",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm">{station.name}</span>
        <Pill tone={stateTone(station.state)} dot>
          {stateLabel(station.state)}
        </Pill>
      </div>
      <p className="mt-1.5 font-mono text-xs text-faint">
        lag {lag} · {Math.round(station.throughput_per_min)}/min · dlq {station.dlq_depth}
      </p>
      <div className="mt-2">
        <Meter
          value={station.limit > 0 ? station.in_flight : 0}
          max={station.limit > 0 ? station.limit : 1}
          tone={isSaturated(station) ? "warn" : "accent"}
          size={5}
          label={`${station.name} in-flight`}
        />
        <p className="mt-1 font-mono text-xs text-faint">{inFlightLabel(station)}</p>
      </div>
      <div className="mt-2.5 flex gap-2">
        <ActionButton
          variant="warn"
          size="sm"
          disabled={!enabled}
          onClick={() => (primary === "pause" ? onPause(station.name) : onResume(station.name))}
        >
          {(primary === "pause" ? "Pause" : "Resume") + suffix}
        </ActionButton>
        <ActionButton
          variant="outline"
          size="sm"
          disabled={!enabled || !canDrain(station.state)}
          onClick={() => onDrain(station.name)}
        >
          {"Drain" + suffix}
        </ActionButton>
      </div>
    </li>
  );
}
