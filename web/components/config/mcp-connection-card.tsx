"use client";

import { useState, useTransition } from "react";

import { testMcpConnection } from "@/app/(shell)/config/actions";
import { Pill } from "@/components/common/pill";
import { MonoLabel } from "@/components/common/mono-label";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

import { SettingRow } from "./setting-row";

type Status = Schemas["McpStatusOut"];
type TestOut = Schemas["McpTestOut"];

/** "HH:MM:SS · tool · N rows" in UTC, or "No calls yet". */
export function lastCallText(last: Status["last_call"] | null | undefined): string {
  if (!last) return "No calls yet";
  const time = new Date(last.at).toISOString().slice(11, 19);
  const rows = last.rows === null || last.rows === undefined ? "" : ` · ${last.rows} rows`;
  return `Last call ${time} · ${last.tool}${rows}`;
}

function testLine(out: TestOut): string {
  if (!out.token_valid || out.error) return out.error ?? "Token not valid";
  const ms = out.probe_ms === null || out.probe_ms === undefined ? "" : ` ${out.probe_ms} ms`;
  return `Token valid · ${out.tools_count} tools · ${out.probe_tool}${ms}`;
}

/** The fusion-sql-mcp connection: health, the staged server URL, facts and Test connection. */
export function McpConnectionCard({
  status,
  entry,
  canEdit,
  canTest,
}: {
  status: Result<Status, ApiError>;
  entry: Schemas["ConfigEntry"] | undefined;
  canEdit: boolean;
  canTest: boolean;
}) {
  const [result, setResult] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [pending, startTransition] = useTransition();

  function runTest() {
    startTransition(async () => {
      const res = await testMcpConnection({});
      if (!res.ok) {
        setFailed(true);
        setResult(res.error.message);
        return;
      }
      setFailed(!res.value.token_valid || Boolean(res.value.error));
      setResult(testLine(res.value));
    });
  }

  const value = status.ok ? status.value : null;
  const healthy = value?.healthy === true;

  return (
    <div className="space-y-3 border-b border-line px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MonoLabel>Connection</MonoLabel>
          <span className="font-mono text-[13px]">fusion-sql-mcp · Fusion reads</span>
        </div>
        {healthy ? (
          <Pill tone="ok" dot>
            Healthy · {value?.latency_ms ?? 0} ms
          </Pill>
        ) : (
          <Pill tone="err" dot>
            Unreachable
          </Pill>
        )}
      </div>
      {entry ? <SettingRow entry={entry} /> : null}
      <dl className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-muted-foreground">
        {value ? (
          <>
            <div>OAuth client {value.client_id}</div>
            {value.secret_in_vault ? <div>Secret in OCI Vault</div> : null}
            <div>Source {value.source}</div>
          </>
        ) : null}
        <div>{lastCallText(value?.last_call)}</div>
      </dl>
      {value?.error ? <p className="text-sm text-err-ink">{value.error}</p> : null}
      <p className="text-sm text-muted-foreground">
        Used for receipt search, invoice and credit memo lookups, lab replays and the
        assistant&apos;s read-only queries. Applying receipts stays on the direct Fusion client.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={!canTest || !canEdit || pending}
          onClick={runTest}
        >
          {pending ? "Testing…" : "Test connection"}
        </Button>
        {!canTest || !canEdit ? (
          <span className="font-mono text-xs text-faint">needs config write</span>
        ) : null}
        <span role="status" className={failed ? "text-sm text-err-ink" : "text-sm text-ok-ink"}>
          {result}
        </span>
      </div>
    </div>
  );
}
