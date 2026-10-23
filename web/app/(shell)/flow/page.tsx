import { RequirePermission } from "@/components/common/require-permission";
import { ErrorAlert } from "@/components/common/error-alert";
import { FlowMonitor } from "@/components/flow/flow-monitor";
import { api } from "@/lib/api/client";
import { getMe, hasPermission } from "@/lib/me";

export default async function FlowPage() {
  const [summary, me] = await Promise.all([api("get", "/flow/summary"), getMe()]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;
  return (
    <RequirePermission me={me.value} permission="items:read" role="VIEWER">
      <FlowMonitor initial={summary} canPauseBacklog={hasPermission(me.value, "backlog:run")} />
    </RequirePermission>
  );
}
