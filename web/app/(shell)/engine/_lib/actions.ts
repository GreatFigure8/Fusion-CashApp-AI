"use server";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import { replayInput, stationActionInput, throttleInput } from "@/lib/engine/schemas";

export const pauseStationAction = apiAction(
  stationActionInput,
  ({ station, reason, expectedVersion }) =>
    api("post", "/engine/stations/{station}/pause", {
      params: { station },
      body: { reason, expected_version: expectedVersion },
    }),
);

export const resumeStationAction = apiAction(
  stationActionInput,
  ({ station, reason, expectedVersion }) =>
    api("post", "/engine/stations/{station}/resume", {
      params: { station },
      body: { reason, expected_version: expectedVersion },
    }),
);

export const drainStationAction = apiAction(
  stationActionInput,
  ({ station, reason, expectedVersion }) =>
    api("post", "/engine/stations/{station}/drain", {
      params: { station },
      body: { reason, expected_version: expectedVersion },
    }),
);

export const setThrottleAction = apiAction(
  throttleInput,
  ({ perStage, applyPerReceipt, reason, expectedVersion }) =>
    api("put", "/engine/throttle", {
      body: {
        per_stage: perStage,
        apply_per_receipt: applyPerReceipt,
        reason,
        expected_version: expectedVersion,
      },
    }),
);

export const replayDeadLettersAction = apiAction(replayInput, ({ eventIds, reason }) =>
  api("post", "/engine/dead-letters/replay", { body: { event_ids: eventIds, reason } }),
);
