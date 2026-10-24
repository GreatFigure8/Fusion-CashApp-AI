import { Pill } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";

/** The Engine-specific pills after env and Live in the TopBar. */
export function EngineTopPills({
  updatedSecondsAgo,
  mcp,
}: Readonly<{
  updatedSecondsAgo: number;
  /** null when the MCP status call failed (403 or unreachable API). */
  mcp: Schemas["McpStatusOut"] | null;
}>) {
  return (
    <>
      <Pill tone="muted">Lag streamed · updated {updatedSecondsAgo} s ago</Pill>
      <Pill tone="locked">Admin only · audited</Pill>
      {mcp === null ? (
        <Pill tone="muted">MCP status unavailable</Pill>
      ) : mcp.healthy ? (
        <Pill tone="ok" dot>
          Fusion reads · MCP healthy {mcp.latency_ms ?? "—"} ms
        </Pill>
      ) : (
        <Pill tone="err" dot>
          MCP unreachable
        </Pill>
      )}
    </>
  );
}
