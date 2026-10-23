import { Suspense } from "react";

import { ErrorAlert } from "@/components/common/error-alert";
import { AppShell } from "@/components/shell/app-shell";
import { ApiDownState, DeniedState, ShellSkeleton } from "@/components/shell/shell-states";
import { StatusFooter } from "@/components/shell/status-footer";
import { StatusFooterServer } from "@/components/shell/status-footer-server";
import { requireSession } from "@/lib/auth/session";
import { getMe } from "@/lib/me";

const API_DOWN_STATUSES = new Set([0, 502, 503, 504]);

async function ShellGate({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me.ok) {
    if (API_DOWN_STATUSES.has(me.error.status)) return <ApiDownState />;
    return (
      <main className="mx-auto w-full max-w-xl p-6">
        <ErrorAlert error={me.error} title="Couldn't load your account" />
      </main>
    );
  }
  if (me.value.roles.length === 0) {
    return <DeniedState requestAccessUrl={me.value.access_request_url} />;
  }
  return (
    <AppShell
      me={me.value}
      env={me.value.env}
      sampleData={me.value.sample_data}
      footer={
        <Suspense fallback={<StatusFooter initial={null} pending />}>
          <StatusFooterServer />
        </Suspense>
      }
    >
      {children}
    </AppShell>
  );
}

export default async function ShellLayout({ children }: LayoutProps<"/">) {
  await requireSession();
  return (
    <Suspense fallback={<ShellSkeleton />}>
      <ShellGate>{children}</ShellGate>
    </Suspense>
  );
}
