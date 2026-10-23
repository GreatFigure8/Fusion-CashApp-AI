"use client";

import { FileXIcon } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { HighlightLayer, type ArtifactHighlight } from "./artifact-viewer/highlight-layer";
import { PdfPages } from "./artifact-viewer/pdf-pages";

export type { ArtifactHighlight };

type Part = Schemas["PartOut"];

type Remote<T> =
  | { url: string; status: "ready"; value: T }
  | { url: string; status: "purged" }
  | { url: string; status: "error" };

const readBuffer = (response: Response) => response.arrayBuffer();
const readText = (response: Response) => response.text();

/** Fetches a part through the web proxy. State is tagged with the URL, so a new URL starts fresh. */
function useRemote<T>(url: string | null, read: (response: Response) => Promise<T>) {
  const [state, setState] = useState<Remote<T> | null>(null);

  useEffect(() => {
    if (url === null) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (response.status === 410) setState({ url, status: "purged" });
        else if (!response.ok) setState({ url, status: "error" });
        else setState({ url, status: "ready", value: await read(response) });
      } catch {
        if (!controller.signal.aborted) setState({ url, status: "error" });
      }
    })();
    return () => controller.abort();
  }, [url, read]);

  return state !== null && state.url === url ? state : null;
}

function partUrl(itemId: number, partNo: number, variant?: "text"): string {
  const base = `/api/items/${itemId}/parts/${partNo}`;
  return variant ? `${base}?variant=${variant}` : base;
}

/** Text with each highlight's quote wrapped in a `<mark>` carrying the field id. */
function MarkedText({
  text,
  highlights,
  activeId,
  onHover,
}: {
  text: string;
  highlights: ArtifactHighlight[];
  activeId: string | null | undefined;
  onHover?: (id: string | null) => void;
}) {
  const spans: { start: number; end: number; highlight: ArtifactHighlight }[] = [];
  for (const highlight of highlights) {
    if (!highlight.quote) continue;
    const start = text.indexOf(highlight.quote);
    if (start >= 0) spans.push({ start, end: start + highlight.quote.length, highlight });
  }
  spans.sort((a, b) => a.start - b.start);

  const pieces: ReactNode[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // overlapping quotes: the earlier one wins
    pieces.push(<Fragment key={`t${cursor}`}>{text.slice(cursor, span.start)}</Fragment>);
    pieces.push(
      <mark
        key={span.highlight.id}
        data-highlight-id={span.highlight.id}
        title={span.highlight.label}
        onMouseEnter={() => onHover?.(span.highlight.id)}
        onMouseLeave={() => onHover?.(null)}
        className={cn(
          "rounded-[2px] px-0.5 text-foreground",
          span.highlight.id === activeId
            ? "bg-status-progress/40 ring-1 ring-status-progress"
            : "bg-status-waiting/30",
        )}
      >
        {text.slice(span.start, span.end)}
      </mark>,
    );
    cursor = span.end;
  }
  pieces.push(<Fragment key="tail">{text.slice(cursor)}</Fragment>);
  return (
    <pre className="max-h-[70vh] overflow-auto rounded border bg-card p-3 font-mono text-xs whitespace-pre-wrap">
      {pieces}
    </pre>
  );
}

function Purged() {
  return (
    <EmptyState
      icon={FileXIcon}
      title="This artifact was purged under the retention policy."
    />
  );
}

function PartBody({
  itemId,
  part,
  highlights,
  activeId,
  onHover,
}: {
  itemId: number;
  part: Part;
  highlights: ArtifactHighlight[];
  activeId: string | null | undefined;
  onHover?: (id: string | null) => void;
}) {
  const mine = highlights.filter((h) => h.partNo === part.part_no);
  const isPdf = part.kind === "PDF";
  const isImage = part.kind === "IMAGE";
  const url = part.purged ? null : partUrl(itemId, part.part_no, isPdf || isImage ? undefined : "text");
  const buffer = useRemote(isPdf ? url : null, readBuffer);
  const text = useRemote(!isPdf && !isImage ? url : null, readText);
  const [imageFailed, setImageFailed] = useState<string | null>(null);

  if (part.purged) return <Purged />;

  if (isPdf) {
    if (buffer === null) return <Skeleton className="h-96 w-full" />;
    if (buffer.status === "purged") return <Purged />;
    if (buffer.status === "error") return <p className="text-sm text-status-error">Couldn&apos;t load this PDF.</p>;
    return <PdfPages data={buffer.value} highlights={mine} activeId={activeId} onHover={onHover} />;
  }

  if (isImage && url !== null) {
    if (imageFailed === url) {
      return <p className="text-sm text-status-error">Couldn&apos;t load this image.</p>;
    }
    return (
      <div className="relative w-full overflow-hidden rounded border bg-white">
        {/* eslint-disable-next-line @next/next/no-img-element -- an authenticated, uncached proxy URL */}
        <img
          src={url}
          alt={`Artifact part ${part.part_no}`}
          className="block h-auto w-full"
          onError={() => setImageFailed(url)}
        />
        <HighlightLayer highlights={mine} activeId={activeId} onHover={onHover} />
      </div>
    );
  }

  if (text === null) return <Skeleton className="h-64 w-full" />;
  if (text.status === "purged") return <Purged />;
  if (text.status === "error") {
    return <p className="text-sm text-status-error">Couldn&apos;t load this part.</p>;
  }
  return <MarkedText text={text.value} highlights={mine} activeId={activeId} onHover={onHover} />;
}

/** The original artifact (PDF, image or text) with the extracted fields drawn over it. */
export function ArtifactViewer({
  itemId,
  parts,
  highlights,
  activeHighlightId,
  onHighlightHover,
}: {
  itemId: number;
  parts: Part[];
  highlights: ArtifactHighlight[];
  activeHighlightId?: string | null;
  onHighlightHover?: (id: string | null) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  if (parts.length === 0) {
    return <EmptyState icon={FileXIcon} title="This item has no stored artifact." />;
  }
  const part = parts.find((p) => p.part_no === selected) ?? parts[0];
  if (!part) return null;

  return (
    <div data-slot="artifact-viewer" className="flex min-w-0 flex-col gap-2">
      {parts.length > 1 ? (
        <div role="tablist" aria-label="Artifact parts" className="flex flex-wrap gap-1">
          {parts.map((p) => (
            <Button
              key={p.part_no}
              role="tab"
              aria-selected={p.part_no === part.part_no}
              variant={p.part_no === part.part_no ? "secondary" : "ghost"}
              size="xs"
              onClick={() => setSelected(p.part_no)}
            >
              Part {p.part_no} · {p.kind.toLowerCase()}
            </Button>
          ))}
        </div>
      ) : null}
      <PartBody
        key={part.part_no}
        itemId={itemId}
        part={part}
        highlights={highlights}
        activeId={activeHighlightId}
        onHover={onHighlightHover}
      />
    </div>
  );
}
