import type { Metadata } from "next";
import { Suspense } from "react";

import { SkeletonRows } from "@/components/common/skeleton-rows";
import { CandidateReceiptTiles } from "@/components/exceptions/candidate-receipt-tiles";
import { ClassificationOverride } from "@/components/exceptions/classification-override";
import { EditForm } from "@/components/exceptions/edit-form";
import { ExceptionFilterChips } from "@/components/exceptions/exception-filter-chips";
import { ExceptionSheet } from "@/components/exceptions/exception-sheet";
import { ExceptionsFilterBar } from "@/components/exceptions/exceptions-filter-bar";
import { ExceptionsTable } from "@/components/exceptions/exceptions-table";
import {
  FusionAutofix,
  FusionContextSection,
  FusionReceiptPicker,
} from "@/components/exceptions/fusion-context-section";
import { RetryAlert } from "@/components/exceptions/retry-alert";
import { ShowAppliedToggle } from "@/components/exceptions/show-applied-toggle";
import { WhyStuck } from "@/components/exceptions/why-stuck";
import { TopBar } from "@/components/shell/top-bar";
import type { Schemas } from "@/lib/api/types";

import { ERROR_CODES, STAGES } from "./_lib/enums";
import {
  getExceptionCounts,
  getExceptions,
  getFusionContext,
  getItemDetail,
  getItemHistory,
  getMe,
} from "./_lib/queries";
import { isFiltered, parseExceptionFilters, parseWorkItemParam } from "./_lib/search-params";

export const metadata: Metadata = { title: "Exceptions · CashApp" };

/** The most recent reasoning recorded against the item's current error code. */
function lastErrorText(
  history: readonly Schemas["HistoryRowOut"][],
  code: Schemas["ErrorCode"] | null,
): string | null {
  if (!code) return null;
  let latest: Schemas["HistoryRowOut"] | null = null;
  for (const row of history) {
    if (row.error_code === code && (!latest || row.at > latest.at)) latest = row;
  }
  if (!latest) return null;
  const message = latest.payload?.["message"];
  return latest.reasoning ?? (typeof message === "string" ? message : null);
}

function ContextFallback(): React.JSX.Element {
  return <SkeletonRows rows={5} height={40} caption="Reading Fusion context…" />;
}

/** Provenance tag per line number, from the adjudicated extraction. */
function lineSources(
  final: NonNullable<Schemas["ExtractionOut"]["final"]>,
  provenance: Schemas["ExtractionOut"]["provenance"],
): Record<number, string> {
  const sources: Record<number, string> = {};
  final.lines.forEach((line, index) => {
    const tag = provenance[`lines[${index}]`];
    if (tag) sources[line.line_no] = tag;
  });
  return sources;
}

export default async function ExceptionsPage(props: PageProps<"/exceptions">) {
  const filters = parseExceptionFilters(await props.searchParams);
  const itemId = parseWorkItemParam(filters.item);

  // Started together (DF-4); the Fusion context is streamed and never awaited here.
  const listPromise = getExceptions(filters);
  const countsPromise = getExceptionCounts(filters);
  const mePromise = getMe();
  const detailPromise = itemId !== null ? getItemDetail(itemId) : null;
  const historyPromise = itemId !== null ? getItemHistory(itemId) : null;
  const contextPromise = itemId !== null ? getFusionContext(itemId) : null;

  const [list, me, counts] = await Promise.all([listPromise, mePromise, countsPromise]);
  if (!me.ok) return <RetryAlert error={me.error} title="Couldn't load your profile" />;
  if (!list.ok) return <RetryAlert error={list.error} title="Couldn't load the exceptions" />;

  const can = (permission: Schemas["Permission"]) => me.value.permissions.includes(permission);
  const canWork = can("items:work");
  const canOverride = can("classification:override");
  const canReverse = can("apply:reverse");

  let sheet: React.ReactNode = null;
  if (itemId !== null && detailPromise && historyPromise && contextPromise) {
    const [detail, history] = await Promise.all([detailPromise, historyPromise]);
    if (!detail.ok) {
      sheet = <RetryAlert error={detail.error} title={`Couldn't open WI-${itemId}`} />;
    } else {
      const { item, extraction } = detail.value;
      const historyRows = history.ok ? history.value.items : [];
      const final = extraction.final ?? null;
      sheet = (
        <ExceptionSheet
          itemId={itemId}
          me={me.value.subject}
          canWork={canWork}
          item={item}
          lock={detail.value.lock ?? null}
          final={final}
        >
          <WhyStuck
            errorCode={item.last_error_code ?? null}
            summary={item.escalation_summary ?? null}
            lastError={lastErrorText(historyRows, item.last_error_code ?? null)}
            candidates={
              <Suspense fallback={<SkeletonRows rows={2} />}>
                <CandidateReceiptTiles context={contextPromise} />
              </Suspense>
            }
          />
          <Suspense fallback={<SkeletonRows rows={3} />}>
            <FusionAutofix context={contextPromise} itemState={item.state} />
          </Suspense>
          {item.state === "ARCHIVED" && canOverride ? (
            <ClassificationOverride itemId={itemId} />
          ) : null}
          {final ? (
            <EditForm final={final} lineSources={lineSources(final, extraction.provenance)} />
          ) : null}
          <Suspense fallback={null}>
            <FusionReceiptPicker context={contextPromise} errorCode={item.last_error_code ?? null} />
          </Suspense>
          <Suspense fallback={<ContextFallback />}>
            <FusionContextSection
              context={contextPromise}
              currency={item.currency ?? null}
              canReverse={canReverse}
            />
          </Suspense>
          {!history.ok ? (
            <RetryAlert error={history.error} title="Couldn't load the history" />
          ) : null}
        </ExceptionSheet>
      );
    }
  }

  return (
    <div className="grid min-w-0 gap-4">
      <TopBar title="Exceptions">
        <ShowAppliedToggle />
      </TopBar>
      <Suspense fallback={null}>
        <ExceptionFilterChips filters={filters} counts={counts.chips} />
      </Suspense>
      <ExceptionsFilterBar
        filters={filters}
        errorCodeOptions={ERROR_CODES}
        stageOptions={STAGES}
        canSeeArchived={canOverride}
      />
      <div className="flex min-w-0 flex-wrap items-start gap-4">
        <div className="min-w-0 flex-[999_1_480px]">
          <Suspense fallback={<SkeletonRows rows={10} height={36} caption="Reading exceptions…" />}>
            <ExceptionsTable
              list={list.value}
              filtered={isFiltered(filters)}
              canWork={canWork}
              meSubject={me.value.subject}
              selectedId={itemId}
              appliedHidden={counts.appliedHidden}
              showApplied={filters.includeAutoApplied}
            />
          </Suspense>
        </div>
        <Suspense fallback={null}>{sheet}</Suspense>
      </div>
    </div>
  );
}
