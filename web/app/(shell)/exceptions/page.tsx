import type { Metadata } from "next";
import { Suspense } from "react";

import { ClassificationOverride } from "@/components/exceptions/classification-override";
import { EditForm } from "@/components/exceptions/edit-form";
import { ExceptionSheet } from "@/components/exceptions/exception-sheet";
import { ExceptionsFilterBar } from "@/components/exceptions/exceptions-filter-bar";
import { ExceptionsTable } from "@/components/exceptions/exceptions-table";
import { FusionContextSection } from "@/components/exceptions/fusion-context-section";
import { RetryAlert } from "@/components/exceptions/retry-alert";
import { WhyStuck } from "@/components/exceptions/why-stuck";
import { TopBar } from "@/components/shell/top-bar";
import { HistoryTimeline } from "@/components/common/history-timeline";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/types";

import { ERROR_CODES, STAGES } from "./_lib/enums";
import {
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
  return (
    <div className="grid gap-3" aria-busy="true" aria-label="Loading Fusion context">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

export default async function ExceptionsPage(props: PageProps<"/exceptions">) {
  const filters = parseExceptionFilters(await props.searchParams);
  const itemId = parseWorkItemParam(filters.item);

  // Started together (DF-4); the Fusion context is streamed and never awaited here.
  const listPromise = getExceptions(filters);
  const mePromise = getMe();
  const detailPromise = itemId !== null ? getItemDetail(itemId) : null;
  const historyPromise = itemId !== null ? getItemHistory(itemId) : null;
  const contextPromise = itemId !== null ? getFusionContext(itemId) : null;

  const [list, me] = await Promise.all([listPromise, mePromise]);
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
          />
          {item.state === "ARCHIVED" && canOverride ? (
            <ClassificationOverride itemId={itemId} />
          ) : null}
          {final ? <EditForm final={final} /> : null}
          <Suspense fallback={<ContextFallback />}>
            <FusionContextSection
              context={contextPromise}
              errorCode={item.last_error_code ?? null}
              currency={item.currency ?? null}
              canReverse={canReverse}
            />
          </Suspense>
          <Collapsible>
            <CollapsibleTrigger className="text-sm font-medium underline-offset-4 hover:underline">
              Full history
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3">
              {history.ok ? (
                <HistoryTimeline entries={historyRows} />
              ) : (
                <RetryAlert error={history.error} title="Couldn't load the history" />
              )}
            </CollapsibleContent>
          </Collapsible>
        </ExceptionSheet>
      );
    }
  }

  return (
    <div className="grid gap-4">
      <TopBar title="Exceptions" />
      <ExceptionsFilterBar
        filters={filters}
        errorCodeOptions={ERROR_CODES}
        stageOptions={STAGES}
        canSeeArchived={canOverride}
      />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <ExceptionsTable list={list.value} filtered={isFiltered(filters)} canWork={canWork} />
      </Suspense>
      <Suspense fallback={null}>{sheet}</Suspense>
    </div>
  );
}
