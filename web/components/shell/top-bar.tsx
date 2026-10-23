"use client";

import { SearchIcon } from "lucide-react";
import type { ReactNode } from "react";

import { useShellSession } from "@/components/common/shell-session";
import { LiveDot } from "@/components/common/live-dot";
import { Pill } from "@/components/common/pill";
import { EnvPill } from "@/components/shell/env-badge";
import { useFlowStream } from "@/components/shell/flow-stream";
import { useCommandPalette } from "@/components/shell/command-palette";
import { GlassPanel } from "@/components/common/glass-panel";

function LivePill() {
  const { status, retries } = useFlowStream();
  const tone = status === "live" ? "ok" : status === "reconnecting" ? "warn" : "err";
  const label =
    status === "live"
      ? "Live"
      : status === "reconnecting"
        ? retries > 0
          ? `Reconnecting… (retry ${retries})`
          : "Reconnecting…"
        : "Disconnected";
  return (
    <span role="status" data-status={status}>
      <Pill tone={tone}>
        <LiveDot tone={tone} pulse={status === "live"} />
        {label}
      </Pill>
    </span>
  );
}

function SearchField() {
  const palette = useCommandPalette();
  return (
    <button
      type="button"
      onClick={palette.open}
      aria-label="Search items"
      className="flex min-h-9 min-w-[260px] max-w-full items-center gap-2 rounded-[10px] border border-line-strong bg-surface-2 px-3 text-left text-[13px] text-muted-foreground hover:bg-white/5"
    >
      <SearchIcon aria-hidden className="size-4 shrink-0" />
      <span className="flex-1 truncate">
        <span className="sr-only">Search. </span>Item, receipt, invoice
      </span>
      <kbd className="rounded border border-line-strong bg-surface-3 px-1.5 font-mono text-[10px]">
        ⌘K
      </kbd>
    </button>
  );
}

/** The per-page glass bar: title, environment, live state, sample-data flag and page controls. */
export function TopBar({
  title,
  crumb,
  pills,
  search = true,
  children,
}: {
  title: string;
  crumb?: string;
  pills?: ReactNode;
  search?: boolean;
  children?: ReactNode;
}) {
  const { env, sampleData } = useShellSession();
  return (
    <GlassPanel as="header" className="flex flex-wrap items-center gap-x-3 gap-y-2 px-[18px] py-3">
      <div className="flex min-w-0 items-baseline gap-2">
        {crumb ? (
          <>
            <span className="font-mono text-label text-muted-foreground">{crumb}</span>
            <span aria-hidden className="text-faint">
              /
            </span>
          </>
        ) : null}
        <h1 className="text-lg font-semibold tracking-[-0.01em]">{title}</h1>
      </div>
      <EnvPill env={env} />
      <LivePill />
      {sampleData ? <Pill tone="muted">Sample data</Pill> : null}
      {pills}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {children}
        {search ? <SearchField /> : null}
      </div>
    </GlassPanel>
  );
}
