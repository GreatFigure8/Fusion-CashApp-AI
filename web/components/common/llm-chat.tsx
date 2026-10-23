"use client";

import { useEffect, useState } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { StateCard } from "@/components/common/state-card";
import { cn } from "@/lib/utils";

import { fetchChatTools } from "./llm-chat/chat-server-actions";
import { ActionChips } from "./llm-chat/action-chips";
import type { UploadLimits } from "./llm-chat/attach";
import {
  TOOL_GROUPS,
  type ChatContextRef,
  type ChatMessageOut,
  type ChatToolsOut,
  type PendingConfirm,
  type PromptKey,
  type ResultCard,
  type ToolGroup,
} from "./llm-chat/chat-schemas";
import { ChatHeader, ChatStatus } from "./llm-chat/chat-status";
import { Composer } from "./llm-chat/composer";
import {
  COPY,
  FULL_CHIPS,
  PROMPT_CHIPS,
  TOOL_GROUP_LABELS,
  WELCOME_CHIPS,
  modelLabel,
} from "./llm-chat/defaults";
import { LiveContext } from "./llm-chat/live-context";
import { MessageList } from "./llm-chat/message-list";
import { Suggestions } from "./llm-chat/suggestions";
import { useChat } from "./llm-chat/use-chat";

export type { ChatContextRef, PromptKey, ResultCard, ToolGroup };
export type LlmChatVariant = "dock" | "page" | "compact";

export type LlmChatProps = {
  context: ChatContextRef;
  systemPromptKey: PromptKey;
  variant: LlmChatVariant;
  /** Groups offered this chat; default = every group the person is allowed. */
  tools?: readonly ToolGroup[];
  /** Overrides the chips from defaults.ts. */
  chips?: readonly string[];
  /** Header label for compact and page, for example "Lab assistant". */
  title?: string;
  threadId?: number;
  initialMessages?: readonly ChatMessageOut[];
  /** A confirm that was still open when the thread was loaded. */
  pending?: PendingConfirm | null;
  /** GET /chat/tools; fetched client-side when absent. */
  catalog?: ChatToolsOut;
  /** "Acting as <name> · <role>" in the page header. */
  actingAs?: string;
  uploads?: UploadLimits;
  /** Called once per `tool_finished` that carries a result card, in every variant. */
  onToolResult?: (card: ResultCard) => void;
  className?: string;
};

export const DOCK_INPUT_ID = "assistant-dock-input";

function useCatalog(given: ChatToolsOut | undefined): ChatToolsOut | null {
  const [fetched, setFetched] = useState<ChatToolsOut | null>(null);
  useEffect(() => {
    if (given !== undefined) return;
    let current = true;
    void fetchChatTools().then((r) => {
      if (current && r.ok) setFetched(r.value);
    });
    return () => {
      current = false;
    };
  }, [given]);
  return given ?? fetched;
}

/** The one LLM chat in the app: every place a person talks to the model renders this. */
export function LlmChat({
  context,
  systemPromptKey,
  variant,
  tools,
  chips,
  title,
  threadId,
  initialMessages,
  pending,
  catalog: givenCatalog,
  actingAs,
  uploads,
  onToolResult,
  className,
}: LlmChatProps) {
  const catalog = useCatalog(givenCatalog);
  const chat = useChat({
    context,
    systemPromptKey,
    toolGroups: tools ?? null,
    threadId,
    initialMessages,
    pending,
    onToolResult,
  });
  const { state, send, confirm, cancel, stop, retry } = chat;
  const streaming = state.phase === "streaming";
  const [collapsed, setCollapsed] = useState(false);

  const allowed = TOOL_GROUPS.filter((g) => catalog?.find((c) => c.group === g)?.allowed ?? false);
  const offered = (tools ?? allowed).filter((g) => allowed.includes(g));
  const toolLabels = offered.map((g) => TOOL_GROUP_LABELS[g]);

  const shownChips = chips ?? (variant === "page" ? FULL_CHIPS : PROMPT_CHIPS[systemPromptKey]);
  const connected = state.phase !== "disconnected";
  const label = modelLabel(state.modelId);
  const hasMessages = state.messages.length > 0;
  const onSend = (text: string, uploadIds: readonly string[] = []) => send(text, uploadIds);
  const fullScreenHref = state.threadId === null ? "/assistant" : `/assistant?thread=${state.threadId}`;

  const banners = (
    <>
      {state.phase === "error" && state.error ? (
        state.error.code === "FORBIDDEN" ? (
          <StateCard
            kind="denied"
            headline={state.error.message}
            body={COPY.deniedBody}
            actions={null}
          />
        ) : (
          <ChatStatus kind="error" code={state.error.code} message={state.error.message} onRetry={retry} />
        )
      ) : null}
      {state.phase === "disconnected" ? <ChatStatus kind="disconnected" onRetry={retry} /> : null}
    </>
  );

  const thread = (
    <MessageList
      messages={state.messages}
      streaming={streaming}
      onConfirm={confirm}
      onCancel={(id) => void cancel(id)}
      onDiscard={(id) => onSend(`Discard candidate ${id}`)}
      empty={
        <Suggestions
          suggestions={variant === "page" ? WELCOME_CHIPS : shownChips}
          disabled={streaming}
          onPick={(t) => onSend(t)}
        />
      }
    />
  );

  if (variant === "dock") {
    return (
      <div className={cn("flex flex-col gap-2", className)} data-slot="llm-chat" data-variant="dock">
        {hasMessages && !collapsed ? (
          <GlassPanel className="flex max-h-[50vh] min-h-0 flex-col overflow-hidden">
            <div className="flex min-h-0 flex-1 flex-col">{thread}</div>
          </GlassPanel>
        ) : null}
        <div className="px-1">{banners}</div>
        <ActionChips chips={shownChips} disabled={streaming} onPick={(t) => onSend(t)} scroll className="px-1" />
        <Composer
          form="dock"
          streaming={streaming}
          onSend={onSend}
          onStop={stop}
          fullScreenHref={fullScreenHref}
          inputId={DOCK_INPUT_ID}
        />
        <div className="flex items-center justify-between px-2 text-[12px] text-soft">
          <span>{COPY.dockHint}</span>
          {hasMessages ? (
            <button type="button" className="underline-offset-2 hover:underline" onClick={() => setCollapsed((c) => !c)}>
              {collapsed ? "Show thread" : "Hide thread"}
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (variant === "compact") {
    return (
      <div
        className={cn("flex h-full min-h-0 flex-col gap-2", className)}
        data-slot="llm-chat"
        data-variant="compact"
      >
        <ChatHeader title={title ?? "Assistant"} connected={connected} modelLabel={label} />
        {toolLabels[0] ? (
          <p className="px-3">
            <span className="rounded-full border border-line bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-soft">
              {toolLabels[0]}
            </span>
          </p>
        ) : null}
        {thread}
        <div className="flex flex-col gap-2 px-3 pb-3">
          {banners}
          <Composer form="compact" streaming={streaming} onSend={onSend} onStop={stop} />
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)} data-slot="llm-chat" data-variant="page">
      <ChatHeader title={title ?? "Assistant"} connected={connected} modelLabel={label} actingAs={actingAs} />
      <div className="flex min-h-0 flex-1 flex-wrap gap-4 overflow-y-auto p-4 lg:flex-nowrap">
        <div className="flex min-h-[60vh] min-w-0 flex-[3_1_480px] flex-col gap-3 lg:min-h-0">
          {thread}
          <div className="mx-auto flex w-full max-w-[880px] flex-col gap-3 px-4">
            {banners}
            <ActionChips chips={shownChips} disabled={streaming} onPick={(t) => onSend(t)} />
            <Composer
              form="full"
              streaming={streaming}
              onSend={onSend}
              onStop={stop}
              toolLabels={toolLabels}
              uploadLimits={uploads}
            />
          </div>
        </div>
        <LiveContext tools={catalog} className="flex-[1_1_280px]" />
      </div>
    </div>
  );
}
