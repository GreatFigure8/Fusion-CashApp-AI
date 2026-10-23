"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import { ActionChips } from "./action-chips";
import { AssistantMarkdown } from "./assistant-markdown";
import type { ChatActionHandler, ChatActionSpec, ChatMessage } from "./chat-schemas";

type MessageListProps = {
  messages: readonly ChatMessage[];
  /** The last assistant message is still receiving tokens. */
  streaming: boolean;
  actions: readonly ChatActionSpec[];
  onAction?: ChatActionHandler;
  empty: ReactNode;
  className?: string;
};

export function MessageList({
  messages,
  streaming,
  actions,
  onAction,
  empty,
  className,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const tail = last ? `${last.id}:${last.content.length}` : "";

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [tail]);

  return (
    <ScrollArea className={cn("min-h-0 flex-1", className)}>
      <div
        role="log"
        aria-live="polite"
        aria-label="Conversation"
        className="flex flex-col gap-3 p-3"
      >
        {messages.length === 0 ? empty : null}
        {messages.map((m) =>
          m.role === "user" ? (
            <div
              key={m.id}
              className="ml-auto max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm break-words whitespace-pre-wrap"
            >
              {m.content}
            </div>
          ) : (
            <div key={m.id} className="max-w-full">
              {m.content.length > 0 ? <AssistantMarkdown>{m.content}</AssistantMarkdown> : null}
              {streaming && m === last ? (
                <span
                  aria-hidden="true"
                  data-slot="chat-caret"
                  className="inline-block animate-pulse text-muted-foreground"
                >
                  ▍
                </span>
              ) : null}
              {m.stopped ? <p className="text-xs text-muted-foreground">Stopped</p> : null}
              <ActionChips proposed={m.actions} specs={actions} onAction={onAction} />
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
