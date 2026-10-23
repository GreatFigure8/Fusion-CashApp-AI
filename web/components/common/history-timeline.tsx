"use client";

import { ChevronRightIcon, CopyIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { Schemas } from "@/lib/api/types";
import { formatDateTime, formatRelative, humanizeEnum } from "@/lib/format";
import { cn } from "@/lib/utils";

export type HistoryEntryView = Schemas["HistoryRowOut"];

const ACTION_LABEL: Record<Schemas["HistoryRowOut"]["action"], string> = {
  STAGE_TRANSITION: "Stage change",
  AUTOFIX_ATTEMPT: "Auto-fix attempt",
  HUMAN_ACTION: "Human action",
  FUSION_WRITE: "Fusion write",
  DECISION: "Decision",
  LOCK: "Lock",
};

const ACTION_DOT: Record<Schemas["HistoryRowOut"]["action"], string> = {
  STAGE_TRANSITION: "bg-status-progress",
  AUTOFIX_ATTEMPT: "bg-status-attention",
  HUMAN_ACTION: "bg-status-locked",
  FUSION_WRITE: "bg-status-success",
  DECISION: "bg-muted-foreground",
  LOCK: "bg-status-locked",
};

function summary(entry: HistoryEntryView): string {
  const parts: string[] = [];
  if (entry.from_stage || entry.to_stage) {
    parts.push(
      entry.from_stage && entry.to_stage && entry.from_stage !== entry.to_stage
        ? `${humanizeEnum(entry.from_stage)} → ${humanizeEnum(entry.to_stage)}`
        : humanizeEnum(entry.to_stage ?? entry.from_stage ?? ""),
    );
  }
  if (entry.from_state !== entry.to_state && entry.to_state) {
    parts.push(
      entry.from_state
        ? `${humanizeEnum(entry.from_state)} → ${humanizeEnum(entry.to_state)}`
        : humanizeEnum(entry.to_state),
    );
  }
  return parts.join(" · ");
}

function copyPayload(payload: unknown): void {
  void navigator.clipboard
    .writeText(JSON.stringify(payload, null, 2))
    .then(() => toast.success("Payload copied"))
    .catch(() => toast.error("Couldn't copy the payload"));
}

function Entry({ entry, defaultOpen }: { entry: HistoryEntryView; defaultOpen: boolean }) {
  const detail = summary(entry);
  const hasPayload = entry.payload !== null;
  const header = (
    <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
      <span className="flex flex-wrap items-center gap-x-2 text-[13px] font-medium">
        {ACTION_LABEL[entry.action]}
        {detail ? <span className="font-normal text-muted-foreground">{detail}</span> : null}
        {entry.error_code ? (
          <span className="font-mono text-xs text-status-error">{entry.error_code}</span>
        ) : null}
      </span>
      <span className="text-xs text-muted-foreground">
        {entry.actor_name} ·{" "}
        <time dateTime={entry.at} title={formatDateTime(entry.at)}>
          {formatRelative(entry.at)}
        </time>
      </span>
    </span>
  );

  return (
    <li className="relative pl-5" data-history-id={entry.id}>
      <span
        aria-hidden
        className={cn("absolute top-1.5 left-0 size-2 rounded-full", ACTION_DOT[entry.action])}
      />
      {hasPayload ? (
        <Collapsible defaultOpen={defaultOpen}>
          <CollapsibleTrigger className="group flex w-full items-start gap-1 rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring">
            {header}
            <ChevronRightIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-data-panel-open:rotate-90" />
          </CollapsibleTrigger>
          {entry.reasoning ? <p className="mt-1 text-xs">{entry.reasoning}</p> : null}
          <CollapsibleContent>
            <div className="relative mt-2 rounded-md border bg-muted/40">
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Copy payload"
                className="absolute top-1 right-1"
                onClick={() => copyPayload(entry.payload)}
              >
                <CopyIcon />
              </Button>
              <pre className="max-h-72 overflow-auto p-2 pr-8 font-mono text-xs">
                {JSON.stringify(entry.payload, null, 2)}
              </pre>
            </div>
          </CollapsibleContent>
        </Collapsible>
      ) : (
        <>
          {header}
          {entry.reasoning ? <p className="mt-1 text-xs">{entry.reasoning}</p> : null}
          {entry.purged ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Payload removed under the retention policy.
            </p>
          ) : null}
        </>
      )}
    </li>
  );
}

/** Every transition, auto-fix and human action of an item; an entry expands to its payload. */
export function HistoryTimeline({
  entries,
  emptyLabel = "No history yet.",
  defaultExpandedId,
}: {
  entries: HistoryEntryView[];
  emptyLabel?: string;
  defaultExpandedId?: number;
}) {
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }
  return (
    <ol data-slot="history-timeline" className="relative flex flex-col gap-4 border-l pl-1">
      {entries.map((entry) => (
        <Entry key={entry.id} entry={entry} defaultOpen={entry.id === defaultExpandedId} />
      ))}
    </ol>
  );
}
