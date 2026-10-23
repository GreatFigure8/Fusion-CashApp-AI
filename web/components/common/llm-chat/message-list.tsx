"use client";

import { Fragment, useEffect, useRef, type ReactNode } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import { AssistantMarkdown } from "./assistant-markdown";
import { messageText, type ChatMessage, type MessagePart, type ToolRow } from "./chat-reducer";
import { ConfirmCard } from "./confirm-card";
import { ResultCardView } from "./result-cards";
import { ToolActivity } from "./tool-activity";

type MessageListProps = {
  messages: readonly ChatMessage[];
  /** The last assistant message is still receiving tokens. */
  streaming: boolean;
  empty: ReactNode;
  onConfirm: (callId: string, reason: string) => void;
  onCancel: (callId: string) => void;
  onDiscard?: (candidateId: string) => void;
  className?: string;
};

type Block =
  | { kind: "tools"; rows: ToolRow[]; key: string }
  | { kind: "part"; part: Exclude<MessagePart, { kind: "tool" }>; key: string };

/** Consecutive tool parts form one activity strip. */
function toBlocks(parts: readonly MessagePart[]): Block[] {
  const blocks: Block[] = [];
  parts.forEach((part, i) => {
    if (part.kind === "tool") {
      const tail = blocks[blocks.length - 1];
      if (tail && tail.kind === "tools") tail.rows.push(part.row);
      else blocks.push({ kind: "tools", rows: [part.row], key: `t${i}` });
    } else {
      blocks.push({ kind: "part", part, key: `p${i}` });
    }
  });
  return blocks;
}

export function MessageList({
  messages,
  streaming,
  empty,
  onConfirm,
  onCancel,
  onDiscard,
  className,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const tail = last ? `${last.id}:${last.parts.length}:${messageText(last).length}` : "";

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [tail]);

  return (
    <ScrollArea className={cn("min-h-0 flex-1", className)}>
      <div
        role="log"
        aria-live="polite"
        aria-label="Conversation"
        className="mx-auto flex w-full max-w-[880px] flex-col gap-[18px] px-4 py-6"
      >
        {messages.length === 0 ? empty : null}
        {messages.map((m) =>
          m.role === "user" ? (
            <div
              key={m.id}
              className="ml-auto max-w-[78%] rounded-xl border border-line-strong bg-surface-3 px-3.5 py-2.5 text-[15.5px] break-words whitespace-pre-wrap"
            >
              {messageText(m)}
            </div>
          ) : (
            <div key={m.id} className="flex max-w-full flex-col gap-3">
              {toBlocks(m.parts).map((b) => (
                <Fragment key={b.key}>
                  {b.kind === "tools" ? (
                    <ToolActivity rows={b.rows} />
                  ) : b.part.kind === "text" ? (
                    <AssistantMarkdown>{b.part.text}</AssistantMarkdown>
                  ) : b.part.kind === "confirm" ? (
                    <ConfirmCard
                      callId={b.part.callId}
                      tool={b.part.tool}
                      preview={b.part.preview}
                      decision={b.part.decision}
                      onConfirm={onConfirm}
                      onCancel={onCancel}
                    />
                  ) : (
                    <ResultCardView card={b.part.card} onDiscard={onDiscard} />
                  )}
                </Fragment>
              ))}
              {streaming && m === last ? (
                <span
                  aria-hidden="true"
                  data-slot="chat-caret"
                  className="inline-block text-soft motion-safe:animate-pulse"
                >
                  ▍
                </span>
              ) : null}
              {m.stopped ? <p className="text-xs text-soft">Stopped</p> : null}
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
