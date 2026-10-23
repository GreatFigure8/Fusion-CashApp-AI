import type { Metadata } from "next";

import { ErrorAlert } from "@/components/common/error-alert";
import { RequirePermission } from "@/components/common/require-permission";
import { ReviewBoard } from "@/components/review/review-board";
import { TopBar } from "@/components/shell/top-bar";
import { api } from "@/lib/api/client";
import { getMe, hasPermission } from "@/lib/me";

export const metadata: Metadata = { title: "Review · CashApp" };

const FIRST_PAGE = 50;

export default async function ReviewPage() {
  // Started together (DF-4).
  const [me, queue, quota, limits] = await Promise.all([
    getMe(),
    api("get", "/review/queue", { query: { offset: 0, limit: FIRST_PAGE } }),
    api("get", "/review/quota"),
    api("get", "/review/limits"),
  ]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;
  if (!queue.ok) return <ErrorAlert error={queue.error} title="Couldn't load the review queue" />;
  if (!limits.ok) return <ErrorAlert error={limits.error} title="Couldn't load the upload limits" />;

  return (
    <RequirePermission me={me.value} permission="items:read" role="VIEWER">
      <div className="flex flex-col gap-4">
        <TopBar
          title="Review"
          pills={
            quota.ok ? (
              <span className="ml-auto text-[12.5px] text-muted-foreground">
                Today{" "}
                <span className="font-mono text-foreground">
                  {quota.value.used} / {quota.value.limit}
                </span>{" "}
                uploads
              </span>
            ) : null
          }
        />
        <ReviewBoard
          initialRows={queue.value.items}
          limits={limits.value}
          canWork={hasPermission(me.value, "items:work")}
        />
      </div>
    </RequirePermission>
  );
}
