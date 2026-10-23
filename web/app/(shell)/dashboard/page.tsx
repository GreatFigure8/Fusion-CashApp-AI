import type { Metadata } from "next";

import { ErrorAlert } from "@/components/common/error-alert";
import { ForbiddenState } from "@/components/common/require-permission";
import { DashboardBoard } from "@/components/dashboard/dashboard-board";
import { WindowControl } from "@/components/dashboard/window-control";
import { TopBar } from "@/components/shell/top-bar";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { getMe, hasPermission } from "@/lib/me";
import { parseDashboardWindow } from "@/lib/metrics/schemas";

export const metadata: Metadata = { title: "Progress" };

export default async function DashboardPage({ searchParams }: PageProps<"/dashboard">) {
  await requireSession("/dashboard");
  const window = parseDashboardWindow(await searchParams);
  const query = { window };

  const [me, summary, money, throughput, autofix, models, activity, cohere] = await Promise.all([
    getMe(),
    api("get", "/metrics/summary", { query }),
    api("get", "/metrics/money-by-currency", { query }),
    api("get", "/metrics/throughput", { query }),
    api("get", "/metrics/autofix", { query }),
    api("get", "/metrics/models", { query }),
    api("get", "/metrics/activity", { query }),
    api("get", "/llm-usage/cohere-utilisation"),
  ]);

  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;
  if (!hasPermission(me.value, "reports:read")) return <ForbiddenState role="VIEWER" />;

  const failed = [summary, money, throughput, autofix, models, activity].find((r) => !r.ok);
  if (failed && !failed.ok) {
    return <ErrorAlert error={failed.error} title="Couldn't load the aggregates" />;
  }
  if (!summary.ok || !money.ok || !throughput.ok || !autofix.ok || !models.ok || !activity.ok) {
    return null;
  }

  return (
    <div className="flex flex-col gap-4">
      <TopBar title="Progress">
        <WindowControl value={window} />
      </TopBar>
      <DashboardBoard
        window={window}
        data={{
          summary: summary.value,
          money: money.value,
          throughput: throughput.value,
          autofix: autofix.value,
          models: models.value,
          activity: activity.value,
          // Unmeasured is null, never 0%: a failed lookup leaves the pill as a dash.
          cohereUtilisationPct: cohere.ok ? cohere.value.best_pct : null,
        }}
      />
    </div>
  );
}
