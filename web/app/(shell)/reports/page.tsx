import type { Metadata } from "next";

import { Pill } from "@/components/common/pill";
import { ForbiddenState } from "@/components/common/require-permission";
import { DailySummaryView } from "@/components/reports/daily-summary-view";
import { PartiallyPaidView } from "@/components/reports/partially-paid-view";
import { ReportBuilder } from "@/components/reports/report-builder";
import { ReportLoadError } from "@/components/reports/report-load-error";
import { ReportsTabs } from "@/components/reports/reports-tabs";
import { TopBar } from "@/components/shell/top-bar";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { todayUtc } from "@/lib/reports/format";
import { parseBuilderSearchParams, parseReportsSearchParams } from "@/lib/reports/schemas";

export const metadata: Metadata = { title: "Reports" };

const RECENT_EXPORTS = 10;

export default async function ReportsPage({ searchParams }: PageProps<"/reports">) {
  await requireSession("/reports");
  const now = new Date();
  const sp = await searchParams;
  const view = parseReportsSearchParams(sp, now);
  const builder = parseBuilderSearchParams(sp);
  const max = todayUtc(now);

  const [exportsResult, panel] = await Promise.all([
    api("get", "/reports/html/exports", { query: { limit: RECENT_EXPORTS } }),
    view.tab === "daily"
      ? api("get", "/reports/daily-summary", { query: { date: view.date } })
      : api("get", "/reports/partially-paid", { query: { from: view.from, to: view.to } }),
  ]);

  if (!exportsResult.ok && exportsResult.error.status === 403) {
    return (
      <>
        <TopBar title="Reports" />
        <ForbiddenState role="VIEWER" />
      </>
    );
  }
  const recent = exportsResult.ok ? exportsResult.value.data : [];

  return (
    <div className="flex flex-col gap-4">
      <TopBar
        title="Reports"
        pills={
          <Pill tone="ok" dot className="ml-auto">
            Preview updates live
          </Pill>
        }
      />
      <ReportBuilder initial={builder} recent={recent} now={now.toISOString()} />
      <ReportsTabs tab={view.tab}>
        {!panel.ok ? (
          panel.error.status === 403 ? (
            <ForbiddenState role="VIEWER" />
          ) : (
            <ReportLoadError
              error={panel.error}
              title={
                view.tab === "daily"
                  ? "Couldn't load the daily summary"
                  : "Couldn't load the partially paid report"
              }
            />
          )
        ) : view.tab === "daily" ? (
          <DailySummaryView
            data={panel.value as Parameters<typeof DailySummaryView>[0]["data"]}
            date={view.date}
            max={max}
          />
        ) : (
          <PartiallyPaidView
            data={panel.value as Parameters<typeof PartiallyPaidView>[0]["data"]}
            from={view.from}
            to={view.to}
            max={max}
          />
        )}
      </ReportsTabs>
    </div>
  );
}
