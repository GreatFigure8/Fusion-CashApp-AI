"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { z } from "zod";

import { useEventStream, type StreamEvent } from "@/hooks/use-event-stream";
import type { StreamPath } from "@/lib/api/stream-paths";

import { cancelToolCall } from "./chat-server-actions";
import { chatReducer, hydratedState, initialChatState, type ChatState } from "./chat-reducer";
import {
  CHAT_STREAM_PATH,
  chatEventSchemas,
  streamErrorSchema,
  type ChatContextRef,
  type ChatMessageOut,
  type PendingConfirm,
  type PromptKey,
  type ResultCard,
  type ToolGroup,
} from "./chat-schemas";

export type UseChatOptions = {
  context: ChatContextRef;
  systemPromptKey: PromptKey;
  /** Narrows the tools offered this chat; null = every group the person is allowed. */
  toolGroups: readonly ToolGroup[] | null;
  threadId?: number | null;
  initialMessages?: readonly ChatMessageOut[];
  pending?: PendingConfirm | null;
  onToolResult?: (card: ResultCard) => void;
};

export type UseChat = {
  state: ChatState;
  send: (text: string, uploadIds?: readonly string[]) => void;
  confirm: (callId: string, reason: string) => void;
  cancel: (callId: string) => Promise<void>;
  stop: () => void;
  retry: () => void;
};

const anyPayload = z.unknown();

function initState(o: Pick<UseChatOptions, "threadId" | "initialMessages" | "pending">): ChatState {
  if (o.threadId && o.initialMessages) {
    return hydratedState(o.threadId, o.initialMessages, o.pending ?? null);
  }
  return initialChatState;
}

/** Chat state over the shared `useEventStream` (a POST stream that is never silently re-posted). */
export function useChat(options: UseChatOptions): UseChat {
  const { context, systemPromptKey, toolGroups } = options;
  const [state, dispatch] = useReducer(chatReducer, options, initState);
  const request = state.request;
  const streaming = state.phase === "streaming" && request !== null;

  const path: StreamPath =
    request?.kind === "confirm"
      ? `/chat/tool-calls/${request.callId}/confirm`
      : CHAT_STREAM_PATH;

  const resultHandler = useRef(options.onToolResult);
  useEffect(() => {
    resultHandler.current = options.onToolResult;
  });
  const emitResult = (card: ResultCard) => resultHandler.current?.(card);

  // Every frame is checked against its own event schema; a malformed frame is dropped.
  const handleEvent = (e: StreamEvent<unknown>) => {
    switch (e.event) {
      case "text_delta": {
        const p = chatEventSchemas.text_delta.safeParse(e.data);
        if (p.success) dispatch({ type: "text_delta", text: p.data.text });
        return;
      }
      case "tool_started": {
        const p = chatEventSchemas.tool_started.safeParse(e.data);
        if (p.success) dispatch({ type: "tool_started", event: p.data });
        return;
      }
      case "tool_progress": {
        const p = chatEventSchemas.tool_progress.safeParse(e.data);
        if (p.success) {
          dispatch({ type: "tool_progress", callId: p.data.call_id, done: p.data.done, total: p.data.total });
        }
        return;
      }
      case "tool_finished": {
        const p = chatEventSchemas.tool_finished.safeParse(e.data);
        if (!p.success) return;
        dispatch({ type: "tool_finished", event: p.data });
        if (p.data.result_card) emitResult(p.data.result_card);
        return;
      }
      case "confirm_required": {
        const p = chatEventSchemas.confirm_required.safeParse(e.data);
        if (p.success) {
          dispatch({
            type: "confirm_required",
            callId: p.data.call_id,
            tool: p.data.tool,
            preview: p.data.preview,
            expiresAt: p.data.expires_at,
          });
        }
        return;
      }
      case "error": {
        const p = chatEventSchemas.error.safeParse(e.data);
        dispatch({
          type: "error",
          error: p.success
            ? p.data
            : {
                code: "INTERNAL_ERROR",
                message: "The assistant hit an unexpected error.",
                call_id: null,
                fatal: true,
                thread_id: null,
              },
        });
        return;
      }
      case "done": {
        const p = chatEventSchemas.done.safeParse(e.data);
        if (p.success) dispatch({ type: "done", event: p.data });
        return;
      }
      default:
        return;
    }
  };

  const handleStreamError = (data: unknown) => {
    const parsed = streamErrorSchema.safeParse(data);
    dispatch({
      type: "stream-error",
      code: parsed.success ? parsed.data.code : "internal_error",
      message: parsed.success ? parsed.data.message : "The assistant hit an unexpected error.",
    });
  };

  const stream = useEventStream<unknown>(path, {
    body: request ? request.body : undefined,
    schema: anyPayload,
    onEvent: handleEvent,
    onStreamError: handleStreamError,
    enabled: streaming,
    reconnect: false,
  });
  const { status, retry: restartStream } = stream;

  // The stream ended (or failed) with no `done` or `error` having arrived.
  useEffect(() => {
    if (state.phase === "streaming" && status === "disconnected") dispatch({ type: "disconnected" });
  }, [state.phase, status]);

  const send = useCallback(
    (text: string, uploadIds: readonly string[] = []) =>
      dispatch({ type: "send", text, context, systemPromptKey, toolGroups, uploadIds }),
    [context, systemPromptKey, toolGroups],
  );
  const confirm = useCallback(
    (callId: string, reason: string) => dispatch({ type: "confirm-sent", callId, reason }),
    [],
  );
  const cancel = useCallback(async (callId: string) => {
    const result = await cancelToolCall(callId);
    // Cancelling an already-decided call (409) leaves the card as the server says; only a
    // success settles it here.
    if (result.ok) dispatch({ type: "cancel-sent", callId });
  }, []);
  const stop = useCallback(() => dispatch({ type: "stop" }), []);
  const retry = useCallback(() => {
    dispatch({ type: "retry" });
    // A new connection key, so the same body is posted again.
    restartStream();
  }, [restartStream]);

  return { state, send, confirm, cancel, stop, retry };
}
