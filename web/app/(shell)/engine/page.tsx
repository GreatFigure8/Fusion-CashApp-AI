import type { Metadata } from "next";

import { ErrorAlert } from "@/components/common/error-alert";
import { RequirePermission } from "@/components/common/require-permission";
import { EngineBoard } from "@/components/engine/engine-board";
import { api } from "@/lib/api/client";
import { getMe, hasPermission } from "@/lib/me";
import { ENGINE_CONTROL } from "@/lib/permissions";

export const metadata: Metadata = { title: "Engine" };

export default async function EnginePage() {
  const me = await getMe();
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;

  const [status, deadLetters, audit, mcp] = await Promise.all([
    api("get", "/engine/status"),
    api("get", "/engine/dead-letters", { query: { offset: 0, limit: 50 } }),
    api("get", "/engine/audit", { query: { offset: 0, limit: 20 } }),
    api("get", "/integrations/mcp/status"),
  ]);

  const failed = [status, deadLetters, audit].find((r) => !r.ok);
  const firstError = failed !== undefined && !failed.ok ? failed.error : null;

  return (
    <RequirePermission me={me.value} permission="reports:read" role="VIEWER">
      {status.ok && deadLetters.ok && audit.ok ? (
        <EngineBoard
          status={status.value}
          deadLetters={deadLetters.value}
          audit={audit.value}
          mcp={mcp.ok ? mcp.value : null}
          canControl={hasPermission(me.value, ENGINE_CONTROL)}
        />
      ) : firstError !== null ? (
        <div className="p-4">
          <ErrorAlert error={firstError} title="Couldn't load the engine" />
        </div>
      ) : null}
    </RequirePermission>
  );
}
