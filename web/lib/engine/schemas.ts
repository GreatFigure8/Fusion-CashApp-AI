import { z } from "zod";

import type { Schemas } from "@/lib/api/types";

/** The web repeats the API's bounds only for early feedback; the API remains the control. */
export const THROTTLE_BOUNDS = {
  perStage: { min: 1, max: 32 },
  applyPerReceipt: { min: 1, max: 8 },
} as const;

export const stationName = z.string().regex(/^[a-z_.]{1,40}$/);
export const reason = z.string().trim().min(1).max(500);
export const expectedVersion = z.number().int().min(0);
export const eventIds = z.array(z.string().min(1).max(64)).min(1).max(100);

export const stationActionInput = z.object({ station: stationName, reason, expectedVersion });

export const throttleInput = z.object({
  perStage: z.number().int().min(THROTTLE_BOUNDS.perStage.min).max(THROTTLE_BOUNDS.perStage.max),
  applyPerReceipt: z
    .number()
    .int()
    .min(THROTTLE_BOUNDS.applyPerReceipt.min)
    .max(THROTTLE_BOUNDS.applyPerReceipt.max),
  reason,
  expectedVersion,
});

export const replayInput = z.object({ eventIds, reason });

export type EngineStatus = Schemas["EngineStatusOut"];

/** Validates the keys the board reads from an SSE `status` frame; anything else is dropped. */
export const engineStatusEventSchema = z.custom<EngineStatus>((value) => {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    Array.isArray(v.stations) &&
    typeof v.bus_healthy === "boolean" &&
    typeof v.config_version === "number" &&
    typeof v.consumer_group === "string"
  );
});
