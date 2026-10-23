import type { Metadata } from "next";
import { z } from "zod";

import { ErrorAlert } from "@/components/common/error-alert";
import { LlmChat } from "@/components/common/llm-chat";
import { RequirePermission } from "@/components/common/require-permission";
import { StateCard } from "@/components/common/state-card";
import { getChatThread, getChatTools } from "@/lib/chat";
import { getMe } from "@/lib/me";

export const metadata: Metadata = { title: "Assistant · CashApp" };

const threadParam = z.coerce.number().int().positive().max(2_147_483_647);
const ASSISTANT_CONTEXT = { kind: "assistant" } as const;

export default async function AssistantPage({ searchParams }: PageProps<"/assistant">) {
  const [params, me, tools] = await Promise.all([searchParams, getMe(), getChatTools()]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;

  const raw = params["thread"];
  const parsed = threadParam.safeParse(Array.isArray(raw) ? raw[0] : raw);
  const thread = parsed.success ? await getChatThread(parsed.data) : null;
  const loaded = thread && thread.ok ? thread.value : null;
  // An unknown or foreign thread starts fresh, with a notice instead of a 404.
  const missing = raw !== undefined && loaded === null;
  const role = me.value.roles[0] ?? "VIEWER";

  return (
    <RequirePermission me={me.value} permission="chat:use" role="OPERATOR">
      <div className="flex h-[calc(100dvh-6rem)] min-h-0 flex-col gap-3">
        {missing ? (
          <StateCard
            kind="empty"
            label="Notice"
            headline="That conversation wasn't found."
            body="Starting a new one."
          />
        ) : null}
        <LlmChat
          variant="page"
          systemPromptKey="assistant"
          context={ASSISTANT_CONTEXT}
          title="Assistant"
          actingAs={`Acting as ${me.value.display_name} · ${role.toLowerCase()}`}
          catalog={tools.ok ? tools.value : undefined}
          threadId={loaded?.id}
          initialMessages={loaded?.messages}
          pending={loaded?.pending ?? null}
        />
      </div>
    </RequirePermission>
  );
}
