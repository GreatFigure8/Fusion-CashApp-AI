"use server";

import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { cancelChatToolCall, chatApi, getChatTools } from "@/lib/chat";
import type { ApiError } from "@/lib/api/errors";
import type { Result } from "@/lib/result";

const callIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,64}$/);

/** Cancels a pending tool call. Nothing runs; the API re-checks the caller. */
export const cancelToolCall = apiAction(callIdSchema, async (callId) => {
  const result = await cancelChatToolCall(callId);
  return result.ok ? { ok: true as const, value: { callId } } : result;
});

// ---- live context ----------------------------------------------------------------------------

const summarySchema = z.object({
  data: z.object({
    automation_rate: z.number().nullable().optional(),
    open_exceptions: z.number().nullable().optional(),
  }),
});

const engineStatusSchema = z.object({
  total_lag: z.number().nullable().optional(),
  stations: z.union([
    z.array(z.object({ state: z.string() }).catchall(z.unknown())),
    z.record(z.string(), z.object({ state: z.string() }).catchall(z.unknown())),
  ]),
});

const mcpStatusSchema = z.object({
  healthy: z.boolean(),
  latency_ms: z.number().nullable().optional(),
});

export type LiveContextValues = {
  automationRate: number | null;
  openExceptions: number | null;
  busLag: number | null;
  applyState: string | null;
  fusionReads: "healthy" | "unhealthy" | "unknown";
};

export type LiveContextSnapshot = {
  /** Each source resolves on its own; null means that source failed. */
  summary: Result<Pick<LiveContextValues, "automationRate" | "openExceptions">, ApiError>;
  engine: Result<Pick<LiveContextValues, "busLag" | "applyState">, ApiError>;
  mcp: Result<LiveContextValues["fusionReads"], ApiError>;
};

function applyStateOf(stations: z.infer<typeof engineStatusSchema>["stations"]): string | null {
  if (Array.isArray(stations)) {
    const found = stations.find((s) => {
      const name = s["station"] ?? s["name"] ?? s["key"];
      return typeof name === "string" && name.toLowerCase() === "apply";
    });
    return found ? found.state : null;
  }
  const found = Object.entries(stations).find(([name]) => name.toLowerCase() === "apply");
  return found ? found[1].state : null;
}

/** One read of the three live-context sources; one failing source never hides the others. */
export async function loadLiveContext(): Promise<LiveContextSnapshot> {
  const [summary, engine, mcp] = await Promise.all([
    chatApi("get", "/metrics/summary", summarySchema, { query: { window: "7d" } }),
    chatApi("get", "/engine/status", engineStatusSchema),
    chatApi("get", "/integrations/mcp/status", mcpStatusSchema),
  ]);
  return {
    summary: summary.ok
      ? {
          ok: true,
          value: {
            automationRate: summary.value.data.automation_rate ?? null,
            openExceptions: summary.value.data.open_exceptions ?? null,
          },
        }
      : summary,
    engine: engine.ok
      ? {
          ok: true,
          value: {
            busLag: engine.value.total_lag ?? null,
            applyState: applyStateOf(engine.value.stations),
          },
        }
      : engine,
    mcp: mcp.ok ? { ok: true, value: mcp.value.healthy ? "healthy" : "unhealthy" } : mcp,
  };
}

/** The tool catalog, for a chat that was not handed one by its server parent. */
export async function fetchChatTools() {
  return getChatTools();
}
