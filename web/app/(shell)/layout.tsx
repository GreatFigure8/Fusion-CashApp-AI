import { Suspense } from "react";

import { ErrorAlert } from "@/components/common/error-alert";
import { AssistantDock } from "@/components/common/llm-chat/dock";
import { AppShell } from "@/components/shell/app-shell";
import { requireSession } from "@/lib/auth/session";
import { getChatTools } from "@/lib/chat";
import { publicEnv } from "@/lib/env.public";
import { getMe } from "@/lib/me";

/** The tool catalog loads in its own boundary: the dock shows at once and fills in. */
async function DockWithTools() {
  const tools = await getChatTools();
  return <AssistantDock catalog={tools.ok ? tools.value : null} />;
}

export default async function ShellLayout({ children }: LayoutProps<"/">) {
  await requireSession();
  const me = await getMe();
  if (!me.ok) {
    return (
      <main className="mx-auto w-full max-w-xl p-6">
        <ErrorAlert error={me.error} title="Couldn't load your account" />
      </main>
    );
  }
  return (
    <AppShell me={me.value} envLabel={publicEnv.NEXT_PUBLIC_ENV_LABEL}>
      {children}
      <Suspense fallback={<AssistantDock catalog={null} />}>
        <DockWithTools />
      </Suspense>
    </AppShell>
  );
}
