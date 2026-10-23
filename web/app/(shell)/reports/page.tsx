import type { Metadata } from "next";

import { ForbiddenState } from "@/components/common/require-permission";
import { DailySummaryView } from "@/components/reports/daily-summary-view";
import { PartiallyPaidView } from "@/components/reports/partially-paid-view";
import { ReportLoadError } from "@/components/reports/report-load-error";
import { ReportsTabs } from "@/components/reports/reports-tabs";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { todayUtc } from "@/lib/reports/format";
import { parseReportsSearchParams } from "@/lib/reports/schemas";

export const metadata: Metadata = { title: "Reports" };

export default async function ReportsPage({ searchParams }: PageProps<"/reports">) {
  await requireSession("/reports");
  const now = new Date();
  const view = parseReportsSearchParams(await searchParams, now);
  const max = todayUtc(now);

  if (view.tab === "daily") {
    const result = await api("get", "/reports/daily-summary", { query: { date: view.date } });
    return (
      <ReportsTabs tab="daily">
        {result.ok ? (
          <DailySummaryView data={result.value} date={view.date} max={max} />
        ) : result.error.status === 403 ? (
          <ForbiddenState role="VIEWER" />
        ) : (
          <ReportLoadError error={result.error} title="Couldn't load the daily summary" />
        )}
      </ReportsTabs>
    );
  }

  const result = await api("get", "/reports/partially-paid", {
    query: { from: view.from, to: view.to },
  });
  return (
    <ReportsTabs tab="partial">
      {result.ok ? (
        <PartiallyPaidView data={result.value} from={view.from} to={view.to} max={max} />
      ) : result.error.status === 403 ? (
        <ForbiddenState role="VIEWER" />
      ) : (
        <ReportLoadError error={result.error} title="Couldn't load the partially paid report" />
      )}
    </ReportsTabs>
  );
}
