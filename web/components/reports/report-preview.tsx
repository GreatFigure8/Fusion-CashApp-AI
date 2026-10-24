"use client";

import * as React from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { previewUrl } from "@/lib/reports/html";
import type { HtmlReportParams } from "@/lib/reports/schemas";

export const PREVIEW_DEBOUNCE_MS = 250;

type Loaded =
  | { kind: "ready"; html: string; hasData: boolean; asOf: string | null }
  | { kind: "error" };

/** What a fetch for one URL produced; `url` says which request it answers. */
type Outcome = { url: string; result: Loaded };

export type PreviewReport = Readonly<{ hasData: boolean | null }>;

const AS_OF = /data-as-of="([^"]{1,16})"/;

/**
 * The export document in a sandboxed iframe (`srcdoc`, no scripts, no same-origin), refetched on
 * every param change. The bytes shown are the bytes the Export button downloads.
 */
export function ReportPreview({
  params,
  onReport,
}: {
  params: HtmlReportParams;
  onReport?: (report: PreviewReport) => void;
}): React.JSX.Element {
  const url = previewUrl(params);
  const [attempt, setAttempt] = React.useState(0);
  const [outcome, setOutcome] = React.useState<Outcome | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
          if (!response.ok) {
            setOutcome({ url, result: { kind: "error" } });
            return;
          }
          const html = await response.text();
          setOutcome({
            url,
            result: {
              kind: "ready",
              html,
              hasData: response.headers.get("X-Report-Has-Data") === "true",
              asOf: AS_OF.exec(html)?.[1] ?? null,
            },
          });
        } catch (e) {
          if (e instanceof DOMException && e.name === "AbortError") return;
          setOutcome({ url, result: { kind: "error" } });
        }
      })();
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [url, attempt]);

  const current = outcome?.url === url ? outcome.result : null;
  const hasData = current?.kind === "ready" ? current.hasData : null;

  React.useEffect(() => {
    onReport?.({ hasData });
  }, [hasData, onReport]);

  return (
    <GlassPanel aria-label="Report preview" className="p-4">
      <div className="flex justify-between pb-3">
        <MonoLabel>Preview · what you export</MonoLabel>
        {current?.kind === "ready" && current.asOf ? (
          <span className="font-mono text-xs text-muted-foreground">As of {current.asOf}</span>
        ) : null}
      </div>
      {current === null ? (
        <StateCard kind="loading" label="Loading · preview" headline="Building the preview">
          <SkeletonRows rows={3} />
        </StateCard>
      ) : current.kind === "error" ? (
        <StateCard
          kind="error"
          label="Error · export"
          headline="The export didn't finish"
          body="The report query timed out. No file was created."
          actions={
            <Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </Button>
          }
        />
      ) : !current.hasData ? (
        <StateCard
          kind="empty"
          headline="Nothing to report yet"
          body="No item finished in this window. Export unlocks when there is data."
        />
      ) : (
        <iframe
          title="Report preview"
          sandbox=""
          srcDoc={current.html}
          className="h-[900px] w-full rounded-xl border-0 bg-white"
        />
      )}
    </GlassPanel>
  );
}
