import { z } from "zod";

/**
 * The slice of `EngineStatusOut` the shell footer reads. Extra fields from the API are ignored,
 * so the engine-control API can grow without touching the footer.
 */
export const engineStatusSchema = z.object({
  bus_healthy: z.boolean(),
  total_lag: z.number(),
  dlq_total: z.number(),
  pollers: z.array(
    z.object({
      name: z.string(),
      interval_seconds: z.number(),
      healthy: z.boolean(),
    }),
  ),
  region: z.string(),
});

export type EngineStatus = z.infer<typeof engineStatusSchema>;

export type FooterView = {
  readonly healthy: boolean;
  readonly lag: number;
  readonly dlq: number;
  readonly pollers: string;
  readonly region: string;
};

function formatInterval(seconds: number): string {
  return seconds >= 60 ? `${Math.round(seconds / 60)}m` : `${seconds}s`;
}

function pollerName(name: string): string {
  return name.replace(/_/g, " ");
}

/** Pure view of the engine status for the footer strip. */
export function formatFooter(status: EngineStatus): FooterView {
  const healthy = status.pollers.filter((poller) => poller.healthy).length;
  const detail = status.pollers
    .map((poller) => `${pollerName(poller.name)} ${formatInterval(poller.interval_seconds)}`)
    .join(" · ");
  const pollers = `Pollers ${healthy}/${status.pollers.length}${detail ? ` · ${detail}` : ""}`;
  return {
    healthy: status.bus_healthy,
    lag: status.total_lag,
    dlq: status.dlq_total,
    pollers,
    region: status.region,
  };
}
