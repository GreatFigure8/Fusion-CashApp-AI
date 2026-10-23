"use client";

import { useEffect } from "react";
import { MessageSquareIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

import { ChatStatus } from "./llm-chat/chat-status";
import { Composer } from "./llm-chat/composer";
import { DEFAULT_SUGGESTIONS, FOOTER_NOTE } from "./llm-chat/defaults";
import { MessageList } from "./llm-chat/message-list";
import { Suggestions } from "./llm-chat/suggestions";
import { useChat, type UseChat } from "./llm-chat/use-chat";
import type {
  ChatActionHandler,
  ChatActionSpec,
  ChatContextRef,
  PromptKey,
} from "./llm-chat/chat-schemas";

export type { ChatActionHandler, ChatActionSpec, ChatContextRef, PromptKey };

export type LlmChatProps = {
  context: ChatContextRef;
  systemPromptKey: PromptKey;
  actions?: readonly ChatActionSpec[];
  /** Required when `actions` is non-empty: without it the chips are disabled. */
  onAction?: ChatActionHandler;
  variant: "panel" | "sheet";
  suggestions?: readonly string[];
  /** Sheet only; optional control. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
};

const NO_ACTIONS: readonly ChatActionSpec[] = [];

type ChatBodyProps = {
  chat: UseChat;
  actions: readonly ChatActionSpec[];
  onAction?: ChatActionHandler;
  suggestions: readonly string[];
  className?: string;
};

function ChatBody({ chat, actions, onAction, suggestions, className }: ChatBodyProps) {
  const { state, send, stop, retry } = chat;
  const streaming = state.phase === "streaming";

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-2", className)} data-slot="llm-chat">
      <MessageList
        messages={state.messages}
        streaming={streaming}
        actions={actions}
        onAction={onAction}
        empty={
          <Suggestions suggestions={suggestions} disabled={streaming} onPick={(text) => send(text)} />
        }
      />
      <div className="flex flex-col gap-2 px-3">
        {state.phase === "error" && state.error ? (
          <ChatStatus
            kind="error"
            code={state.error.code}
            message={state.error.message}
            onRetry={retry}
          />
        ) : null}
        {state.phase === "disconnected" ? <ChatStatus kind="disconnected" onRetry={retry} /> : null}
        <Composer streaming={streaming} onSend={send} onStop={stop} />
        <p className="pb-3 text-xs text-muted-foreground">{FOOTER_NOTE}</p>
      </div>
    </div>
  );
}

/** The one LLM chat in the app: every place a person talks to the model renders this. */
export function LlmChat({
  context,
  systemPromptKey,
  actions = NO_ACTIONS,
  onAction,
  variant,
  suggestions,
  open,
  onOpenChange,
  className,
}: LlmChatProps) {
  const chat = useChat({ context, systemPromptKey, actions });
  const shown = suggestions ?? DEFAULT_SUGGESTIONS[systemPromptKey];
  const missingHandler = actions.length > 0 && onAction === undefined;

  useEffect(() => {
    if (missingHandler) {
      console.warn("LlmChat: `actions` were given without `onAction`; the chips are disabled.");
    }
  }, [missingHandler]);

  const body = (
    <ChatBody
      chat={chat}
      actions={actions}
      onAction={onAction}
      suggestions={shown}
      className={variant === "panel" ? className : undefined}
    />
  );

  if (variant === "panel") {
    return <div className={cn("flex h-full min-h-0 flex-col", className)}>{body}</div>;
  }

  const control = open === undefined ? {} : { open, onOpenChange };
  return (
    <Sheet {...control}>
      <SheetTrigger
        render={
          <Button type="button" variant="outline" size="sm" className={className}>
            <MessageSquareIcon data-icon="inline-start" />
            Ask
          </Button>
        }
      />
      <SheetContent side="right" className="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Ask the assistant</SheetTitle>
          <SheetDescription className="sr-only">
            Ask a question about the current view.
          </SheetDescription>
        </SheetHeader>
        {body}
      </SheetContent>
    </Sheet>
  );
}
