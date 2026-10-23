import type { PillTone } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";

export type Station = Schemas["StationOut"];
export type StationState = Station["state"];

export const CONFLICT_MESSAGE = "Someone changed the engine first; review and try again.";

export function stateCounts(stations: readonly Pick<Station, "state">[]): {
  running: number;
  paused: number;
  draining: number;
} {
  let running = 0;
  let paused = 0;
  let draining = 0;
  for (const s of stations) {
    if (s.state === "RUNNING") running += 1;
    else if (s.state === "DRAINING") draining += 1;
    else paused += 1; // PAUSED and DRAINED
  }
  return { running, paused, draining };
}

export function stateTone(state: StationState): PillTone {
  if (state === "RUNNING") return "ok";
  if (state === "DRAINING") return "accent";
  return "warn";
}

const STATE_LABEL: Readonly<Record<StationState, string>> = {
  RUNNING: "Running",
  PAUSED: "Paused",
  DRAINING: "Draining",
  DRAINED: "Drained",
};

export function stateLabel(state: StationState): string {
  return STATE_LABEL[state];
}

export function isSaturated(s: Pick<Station, "limit" | "in_flight">): boolean {
  return s.limit > 0 && s.in_flight >= s.limit;
}

export function inFlightLabel(s: Pick<Station, "limit" | "in_flight">): string {
  return s.limit > 0 ? `in-flight ${s.in_flight} / ${s.limit}` : "in-flight n/a";
}

export function primaryControl(state: StationState): "pause" | "resume" {
  return state === "PAUSED" || state === "DRAINED" ? "resume" : "pause";
}

export function canDrain(state: StationState): boolean {
  return state === "RUNNING" || state === "PAUSED";
}

export function controlsEnabled(o: { canControl: boolean; busHealthy: boolean }): boolean {
  return o.canControl && o.busHealthy;
}

export function secondsAgo(lastAt: number, now: number): number {
  return Math.max(0, Math.floor((now - lastAt) / 1000));
}

export type EngineAction =
  | { kind: "pause" | "resume" | "drain"; station: string }
  | { kind: "throttle"; perStage: number; applyPerReceipt: number }
  | { kind: "replay"; eventIds: string[] };

export function copyFor(
  action: EngineAction,
  status: Pick<Schemas["EngineStatusOut"], "stations">,
): { title: string; body: string; confirmLabel: string } {
  switch (action.kind) {
    case "pause": {
      const inFlight = status.stations.find((s) => s.name === action.station)?.in_flight ?? 0;
      return {
        title: `Pause the ${action.station} station?`,
        body: `New deliveries stay uncommitted on the bus, so nothing is lost. The ${inFlight} ${action.station}s in flight finish first.`,
        confirmLabel: `Pause ${action.station}`,
      };
    }
    case "resume":
      return {
        title: `Resume the ${action.station} station?`,
        body: "The station starts taking new deliveries from where it stopped.",
        confirmLabel: `Resume ${action.station}`,
      };
    case "drain":
      return {
        title: `Drain the ${action.station} station?`,
        body: "In-flight work finishes, then the station stops taking new deliveries. Nothing is lost.",
        confirmLabel: `Drain ${action.station}`,
      };
    case "throttle":
      return {
        title: "Save throttle?",
        body: `Per stage ${action.perStage}, per receipt ${action.applyPerReceipt}. Fusion applies take about 6 s a line; this is the back-pressure.`,
        confirmLabel: "Save throttle",
      };
    case "replay":
      return {
        title: `Replay ${action.eventIds.length} dead-letter events?`,
        body: "Each event goes back through its stage. Events whose item is locked or done are skipped and listed.",
        confirmLabel: `Replay ${action.eventIds.length} events`,
      };
  }
}
