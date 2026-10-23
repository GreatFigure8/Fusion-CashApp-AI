import {
  ActivityIcon,
  BarChart3Icon,
  DatabaseIcon,
  FlaskConicalIcon,
  GaugeIcon,
  InboxIcon,
  SettingsIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import type { ToolRow } from "./chat-reducer";
import type { ToolGroup } from "./chat-schemas";
import { COPY } from "./defaults";

const GROUP_ICONS: Readonly<Record<ToolGroup, LucideIcon>> = {
  engine: ActivityIcon,
  lab: FlaskConicalIcon,
  settings: SettingsIcon,
  reports: BarChart3Icon,
  review: InboxIcon,
  exceptions: WrenchIcon,
  fusion_reads: DatabaseIcon,
  metrics: GaugeIcon,
};

function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function RowDetail({ row }: { row: ToolRow }) {
  if (row.status === "waiting") return <span className="text-warn">{COPY.waiting}</span>;
  if (row.status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full bg-acc motion-safe:animate-pulse"
        />
        {row.done !== null && row.total !== null
          ? `${row.done.toLocaleString("en-US")} of ${row.total.toLocaleString("en-US")} items`
          : "running"}
      </span>
    );
  }
  if (row.status === "failed") {
    return (
      <span className="text-err">
        {row.error ? `${row.error.message} ${COPY.nothingChanged}` : COPY.nothingChanged}
      </span>
    );
  }
  if (row.status === "cancelled") return <span>cancelled · nothing ran</span>;
  return <span>{row.summary}</span>;
}

/** The bordered strip of tool rows. Every string is rendered as text, never as markup. */
export function ToolActivity({ rows }: { rows: readonly ToolRow[] }) {
  if (rows.length === 0) return null;
  return (
    <ul
      aria-label="Tool activity"
      data-slot="tool-activity"
      className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface-2"
    >
      {rows.map((row) => {
        const Icon = GROUP_ICONS[row.group];
        return (
          <li
            key={row.callId}
            data-status={row.status}
            className="flex items-center gap-3 px-3 py-2 text-[12.5px]"
          >
            <Icon aria-hidden="true" className="size-4 shrink-0 text-soft" />
            <span className="font-mono text-foreground">{row.tool}</span>
            <span className={cn("min-w-0 flex-1 truncate text-soft")}>
              <RowDetail row={row} />
            </span>
            {row.durationMs !== null ? (
              <span className="font-mono text-soft">{formatDuration(row.durationMs)}</span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
