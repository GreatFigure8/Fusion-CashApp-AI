"use client";

import { usePathname } from "next/navigation";

import { DOCK_INPUT_ID, LlmChat } from "@/components/common/llm-chat";

import type { UploadLimits } from "./attach";
import type { ChatToolsOut } from "./chat-schemas";
import { chipsForRoute } from "./defaults";

const ASSISTANT_CONTEXT = { kind: "assistant" } as const;

/** Moves focus to the dock composer (⌘K "Ask the assistant"). No-op where there is no dock. */
export function focusAssistantDock(): void {
  document.getElementById(DOCK_INPUT_ID)?.focus();
}

type AssistantDockProps = {
  /** Null until the catalog has loaded; the dock renders and fetches it itself meanwhile. */
  catalog?: ChatToolsOut | null;
  uploads?: UploadLimits;
};

/**
 * The assistant docked at the bottom of every shell screen. Mounted once in the shell layout, so
 * its thread survives navigation. The full-screen page renders its own chat, so the dock hides.
 */
export function AssistantDock({ catalog, uploads }: AssistantDockProps) {
  const pathname = usePathname();
  if (pathname === "/assistant" || pathname.startsWith("/assistant/")) return null;
  return (
    <div
      data-slot="assistant-dock"
      className="fixed inset-x-0 bottom-0 z-30 mx-auto w-[min(880px,100%)] px-2 pb-2 lg:sticky lg:px-0"
    >
      <LlmChat
        variant="dock"
        context={ASSISTANT_CONTEXT}
        systemPromptKey="assistant"
        chips={chipsForRoute(pathname)}
        catalog={catalog ?? undefined}
        uploads={uploads}
      />
    </div>
  );
}
