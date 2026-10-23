"use client";

import Link from "next/link";
import type { Route } from "next";
import { DownloadIcon, EyeIcon, FileCodeIcon } from "lucide-react";

import { createDataTableColumns, DataTable } from "@/components/common/data-table";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { KpiCard } from "@/components/common/kpi-card";
import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type {
  ExportCardData,
  ReplayCardData,
  ResultCard,
  StateCardData,
  TableCardData,
} from "./chat-schemas";

const LINK_CLASS = buttonVariants({ variant: "outline", size: "sm" });

/** Only same-origin app paths are ever linked from a card; anything else renders as text. */
export function safeCardHref(href: string, allowed: readonly string[]): string | null {
  if (!href.startsWith("/") || href.startsWith("//")) return null;
  return allowed.some((prefix) => href === prefix || href.startsWith(`${prefix}/`) || href.startsWith(`${prefix}?`))
    ? href
    : null;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function StateResultCard({ card }: { card: StateCardData }) {
  return (
    <GlassPanel aria-label={card.title}>
      <PanelHeader title={card.title}>
        <Pill tone={card.status.tone}>{card.status.label}</Pill>
      </PanelHeader>
      <PanelBody>
        {card.stats.length > 0 ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {card.stats.map((s) => (
              <KpiCard key={s.label} label={s.label} value={s.value} size="sm" />
            ))}
          </div>
        ) : null}
        {card.history_id ? (
          <p className="mt-3 text-[12px] text-soft">
            History <span className="font-mono">{card.history_id}</span>
          </p>
        ) : null}
      </PanelBody>
    </GlassPanel>
  );
}

function ReplayResultCard({
  card,
  onDiscard,
}: {
  card: ReplayCardData;
  onDiscard?: (candidateId: string) => void;
}) {
  const labHref = safeCardHref(card.lab_href, ["/lab"]) ?? `/lab?candidate=${encodeURIComponent(card.candidate_id)}`;
  return (
    <GlassPanel aria-label="Replay result">
      <PanelHeader title="Replay result">
        <Pill tone={card.status === "FAILED" ? "err" : card.status === "RUNNING" ? "accent" : "muted"} mono>
          {card.status}
        </Pill>
      </PanelHeader>
      <PanelBody>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KpiCard label="Changed" value={card.changed} size="sm" />
          <KpiCard label="Newly matched" value={`+${card.newly_matched}`} tone="ok" size="sm" />
          <KpiCard label="Newly failed" value={`+${card.newly_failed}`} tone="warn" size="sm" />
          <KpiCard label="Newly ambiguous" value={card.newly_ambiguous} size="sm" />
        </div>
        {card.currencies.length > 0 ? (
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[12px] text-soft">
            {card.currencies.map((c) => (
              <li key={c.currency}>
                {c.currency} affected: {c.newly_matched} matched · {c.newly_unmatched} unmatched · {c.items} items
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Link href={labHref as Route} className={LINK_CLASS}>
            Promote…
          </Link>
          {onDiscard ? (
            <button type="button" className={LINK_CLASS} onClick={() => onDiscard(card.candidate_id)}>
              Discard
            </button>
          ) : null}
          <Link href={labHref as Route} className={LINK_CLASS}>
            Open in Lab
          </Link>
        </div>
      </PanelBody>
    </GlassPanel>
  );
}

function ExportResultCard({ card }: { card: ExportCardData }) {
  const preview = safeCardHref(card.preview_href, ["/api"]);
  const download = safeCardHref(card.download_href, ["/api"]);
  return (
    <GlassPanel aria-label="Export">
      <PanelBody className="flex flex-wrap items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-lg bg-surface-3 text-soft">
          <FileCodeIcon aria-hidden="true" className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-[13px]">{card.filename}</p>
          <MonoLabel className="text-soft">
            {`${formatSize(card.size_bytes)}${card.self_contained ? " · self-contained" : ""}`}
          </MonoLabel>
        </div>
        {preview ? (
          <a href={preview} target="_blank" rel="noopener noreferrer" className={cn(LINK_CLASS, "gap-1")}>
            <EyeIcon aria-hidden="true" /> Preview
          </a>
        ) : null}
        {download ? (
          <a href={download} download={card.filename} className={cn(LINK_CLASS, "gap-1")}>
            <DownloadIcon aria-hidden="true" /> Download
          </a>
        ) : null}
      </PanelBody>
    </GlassPanel>
  );
}

type Row = Record<string, string | number | null>;

function TableResultCard({ card }: { card: TableCardData }) {
  const helper = createDataTableColumns<Row>();
  const columns = card.columns.map((c) =>
    helper.accessor((row) => String(row[c.key] ?? ""), {
      id: c.key,
      header: c.label,
      meta: { align: c.numeric ? "right" : "left", mono: c.numeric },
    }),
  );
  return (
    <GlassPanel aria-label={card.title}>
      <PanelHeader title={card.title}>
        {card.truncated && card.total !== null ? (
          <MonoLabel className="text-soft">{`first ${card.rows.length} of ${card.total}`}</MonoLabel>
        ) : null}
      </PanelHeader>
      <PanelBody flush>
        <DataTable columns={columns} data={card.rows.map((r, i) => ({ ...r, __row: i }))} getRowId={(row) => String(row["__row"])} />
      </PanelBody>
    </GlassPanel>
  );
}

/** One switch over the four card kinds the registry can return. */
export function ResultCardView({
  card,
  onDiscard,
}: {
  card: ResultCard;
  onDiscard?: (candidateId: string) => void;
}) {
  switch (card.kind) {
    case "state_card":
      return <StateResultCard card={card} />;
    case "replay_card":
      return <ReplayResultCard card={card} onDiscard={onDiscard} />;
    case "export_card":
      return <ExportResultCard card={card} />;
    case "table_card":
      return <TableResultCard card={card} />;
  }
}
