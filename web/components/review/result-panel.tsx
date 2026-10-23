"use client";

import type { Route } from "next";
import Link from "next/link";

import { ArtifactViewer, type ArtifactHighlight } from "@/components/common/artifact-viewer";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import { SkeletonRows } from "@/components/common/skeleton-rows";
import { StateCard } from "@/components/common/state-card";
import { statusToken, STATUS_PILL_TONE } from "@/components/common/status-badge";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import { formatMoney, formatWorkItemId, humanizeEnum } from "@/lib/format";

import { sourcePill } from "./format";

type Result = Schemas["ReviewResultOut"];
type Preview = NonNullable<Result["preview"]>;

const FIELD_LABELS: Readonly<Record<string, string>> = {
  payer_name: "Payer",
  remittance_reference: "Reference",
  payment_amount: "Amount",
  currency: "Currency",
  payment_date: "Date",
};

export type ResultState =
  | { readonly kind: "none" }
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly error: ApiError }
  | { readonly kind: "ready"; readonly result: Result };

function highlightFor(preview: Preview): ArtifactHighlight[] {
  if (preview.region === null) return [];
  return [
    {
      id: "amount",
      label: "Amount",
      partNo: preview.part_no,
      page: preview.page,
      bbox: preview.region,
      quote: null,
    },
  ];
}

function fieldValue(result: Result, field: string, value: string | null): string {
  if (value === null) return "—";
  if (field !== "payment_amount") return value;
  const currency = result.fields.find((f) => f.field === "currency")?.value ?? null;
  return formatMoney(value, currency);
}

/** The result for the selected item: preview, adjudicated fields with their sources, the outcome. */
export function ResultPanel({
  itemId,
  filename,
  state,
}: {
  itemId: number | null;
  filename: string | null;
  state: ResultState;
}): React.JSX.Element {
  const result = state.kind === "ready" ? state.result : null;
  const pillLabel =
    result === null
      ? null
      : `${result.applied ? "Applied" : humanizeEnum(result.status)}${
          result.confidence == null ? "" : ` · ${result.confidence.toFixed(2)}`
        }`;
  const tone = result === null ? "muted" : STATUS_PILL_TONE[statusToken("item_state", result.status)];

  return (
    <GlassPanel aria-label="In-depth review result">
      <PanelHeader
        title={
          <span className="flex flex-col">
            {itemId !== null ? (
              <span className="font-mono text-xs text-muted-foreground">
                {formatWorkItemId(itemId)}
                {filename ? ` · ${filename}` : ""}
              </span>
            ) : null}
            <span>In-depth review result</span>
          </span>
        }
      >
        {pillLabel !== null ? <Pill tone={tone}>{pillLabel}</Pill> : null}
      </PanelHeader>
      <PanelBody>
        {state.kind === "none" ? (
          <StateCard
            kind="empty"
            label="Empty · result"
            headline="Select an item"
            body="Pick a row in the queue to see how the readers and the adjudicator saw it."
          />
        ) : state.kind === "loading" ? (
          <StateCard kind="loading" label="Loading · result" headline="Loading the result">
            <SkeletonRows rows={3} caption="Loading the result" />
          </StateCard>
        ) : state.kind === "error" ? (
          <StateCard
            kind="error"
            label="Error · result"
            headline="Couldn't load the result"
            body={state.error.message}
          />
        ) : (
          <ReadyBody itemId={state.result.item_id} result={state.result} />
        )}
      </PanelBody>
    </GlassPanel>
  );
}

function ReadyBody({ itemId, result }: { itemId: number; result: Result }): React.JSX.Element {
  const preview = result.preview;
  const waiting = result.fields.length === 0;
  return (
    <div className="flex flex-wrap gap-4">
      <div className="flex min-w-[150px] flex-[1_1_150px] flex-col gap-2">
        {preview !== null ? (
          <>
            <ArtifactViewer
              itemId={itemId}
              parts={[
                {
                  kind: preview.kind,
                  media_type: preview.media_type,
                  part_no: preview.part_no,
                  purged: false,
                },
              ]}
              highlights={highlightFor(preview)}
              activeHighlightId="amount"
            />
            <span className="font-mono text-[11px] text-muted-foreground">
              page {preview.page} · amount
            </span>
          </>
        ) : (
          <p className="text-[13px] text-muted-foreground">No stored artifact.</p>
        )}
      </div>
      <div className="flex min-w-0 flex-[2_1_220px] flex-col gap-2">
        {waiting ? (
          <StateCard kind="loading" label="Loading · result" headline="Both readers done, adjudicating…">
            <SkeletonRows rows={3} caption="Both readers done, adjudicating…" />
          </StateCard>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="text-left font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                <th className="px-3 py-2 font-normal">Field</th>
                <th className="px-3 py-2 font-normal">Value</th>
                <th className="px-3 py-2 font-normal">Source</th>
              </tr>
            </thead>
            <tbody>
              {result.fields.map((f) => {
                const pill = sourcePill(f.source);
                return (
                  <tr key={f.field} className="border-t border-line">
                    <td className="px-3 py-2.5 text-muted-foreground">{FIELD_LABELS[f.field] ?? f.field}</td>
                    <td className="px-3 py-2.5 font-mono">{fieldValue(result, f.field, f.value)}</td>
                    <td className="px-3 py-2.5">
                      <Pill tone={pill.tone}>{pill.label}</Pill>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {result.adjudication_note ? (
          <p className="text-[13px] text-warn-ink">{result.adjudication_note}</p>
        ) : null}
        {result.applied ? (
          <p className="text-[13px] text-muted-foreground">
            Applied to <span className="font-mono">{result.applied.receipt_number}</span> ·{" "}
            {result.applied.lines} {result.applied.lines === 1 ? "line" : "lines"} · residual{" "}
            {result.applied.residual}
          </p>
        ) : null}
        <div className="flex gap-3.5 text-[13px]">
          <Link href={`/items/${itemId}` as Route}>Open item</Link>
          <Link href={`/items/${itemId}#history` as Route}>History</Link>
        </div>
      </div>
    </div>
  );
}
