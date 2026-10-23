"use client";

import { useCallback, useEffect, useReducer } from "react";

import { useEventStream, type StreamEvent } from "@/hooks/use-event-stream";

import { chatReducer, initialChatState, type ChatState } from "./chat-reducer";
import {
  CHAT_STREAM_PATH,
  actionDataSchema,
  chatFrameSchema,
  doneDataSchema,
  streamErrorSchema,
  tokenDataSchema,
  type ChatActionSpec,
  type ChatContextRef,
  type ChatFrame,
  type PromptKey,
} from "./chat-schemas";

export type UseChatOptions = {
  context: ChatContextRef;
  systemPromptKey: PromptKey;
  actions: readonly ChatActionSpec[];
};

export type UseChat = {
  state: ChatState;
  send: (text: string) => void;
  stop: () => void;
  retry: () => void;
};

/** Chat state over s31's `useEventStream` (a POST stream that is never silently re-posted). */
export function useChat({ context, systemPromptKey, actions }: UseChatOptions): UseChat {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const streaming = state.phase === "streaming" && state.request !== null;

  const handleEvent = (e: StreamEvent<ChatFrame>) => {
    switch (e.event) {
      case "token": {
        const parsed = tokenDataSchema.safeParse(e.data);
        if (parsed.success) dispatch({ type: "token", text: parsed.data.text });
        return;
      }
      case "action": {
        const parsed = actionDataSchema.safeParse(e.data);
        // Defence in depth: the API already filters to the ids we sent.
        if (parsed.success && actions.some((a) => a.id === parsed.data.id)) {
          dispatch({ type: "action", ...parsed.data });
        }
        return;
      }
      case "done":
        if (doneDataSchema.safeParse(e.data).success) dispatch({ type: "done" });
        return;
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

  const stream = useEventStream<ChatFrame>(CHAT_STREAM_PATH, {
    body: state.request ?? undefined,
    schema: chatFrameSchema,
    onEvent: handleEvent,
    onStreamError: handleStreamError,
    enabled: streaming,
    reconnect: false,
  });
  const { status, retry: restartStream } = stream;

  // The stream ended (or the connection failed) while no `done` / `stream-error` had arrived.
  useEffect(() => {
    if (state.phase === "streaming" && status === "disconnected") dispatch({ type: "disconnected" });
  }, [state.phase, status]);

  const send = useCallback(
    (text: string) =>
      dispatch({
        type: "send",
        text,
        context,
        systemPromptKey,
        allowedActions: actions.map((a) => a.id),
      }),
    [context, systemPromptKey, actions],
  );
  const stop = useCallback(() => dispatch({ type: "stop" }), []);
  const retry = useCallback(() => {
    dispatch({ type: "retry" });
    // A new connection key, so the same body is posted again.
    restartStream();
  }, [restartStream]);

  return { state, send, stop, retry };
}
