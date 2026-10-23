import { ErrorAlert } from "@/components/common/error-alert";
import { AppShell } from "@/components/shell/app-shell";
import { requireSession } from "@/lib/auth/session";
import { publicEnv } from "@/lib/env.public";
import { getMe } from "@/lib/me";

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
    </AppShell>
  );
}
