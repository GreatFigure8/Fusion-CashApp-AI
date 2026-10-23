"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";
import type { z } from "zod";

import { createSseParser } from "./sse-parser";
import type { StreamPath } from "./stream-paths";

export type StreamStatus = "live" | "reconnecting" | "disconnected";
export type StreamEvent<T> = { id: string | null; event: string; data: T };
export type UseEventStreamOptions<T> = {
  onEvent: (e: StreamEvent<T>) => void;
  /** Present means POST with this JSON body. */
  body?: unknown;
  /** Validates each data payload; an invalid frame is dropped. */
  schema?: z.ZodType<T>;
  /** Called for `stream-error` frames. */
  onStreamError?: (data: unknown) => void;
  enabled?: boolean;
  /** Defaults to `body === undefined`: a chat prompt is never re-posted. */
  reconnect?: boolean;
  maxRetries?: number;
};

type ConnectionState = { key: string; status: StreamStatus; retries: number };

export const RECONNECT_BASE_MS = 1_000;
export const RECONNECT_CAP_MS = 30_000;

export function reconnectDelay(attempt: number): number {
  return Math.min(RECONNECT_CAP_MS, RECONNECT_BASE_MS * 2 ** attempt);
}

function isFatalStatus(status: number): boolean {
  return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

export function useEventStream<T>(
  path: StreamPath,
  options: UseEventStreamOptions<T>,
): { status: StreamStatus; retries: number; retry: () => void } {
  const { body, schema, enabled = true, maxRetries = 8 } = options;
  const reconnect = options.reconnect ?? body === undefined;

  const bodyKey = JSON.stringify(body ?? null);
  const [attemptKey, setAttemptKey] = useState(0);
  // State is tagged with the connection it belongs to, so a new connection starts fresh
  // without resetting state inside the effect.
  const connectionKey = `${path}|${bodyKey}|${attemptKey}`;
  const [state, setState] = useState<ConnectionState>({
    key: connectionKey,
    status: "reconnecting",
    retries: 0,
  });
  const current =
    state.key === connectionKey
      ? state
      : { key: connectionKey, status: "reconnecting" as const, retries: 0 };
  const patch = useEffectEvent((change: Partial<Omit<ConnectionState, "key">>) =>
    setState((s) => {
      const base: ConnectionState =
        s.key === connectionKey ? s : { key: connectionKey, status: "reconnecting", retries: 0 };
      return { ...base, ...change };
    }),
  );
  const setStatus = useEffectEvent((status: StreamStatus) => patch({ status }));
  const setRetries = useEffectEvent((retries: number) => patch({ retries }));
  const hasBody = body !== undefined;
  const currentBody = useEffectEvent(() => body);

  const handleEvent = useEffectEvent((e: StreamEvent<T>) => options.onEvent(e));
  const handleStreamError = useEffectEvent((data: unknown) => options.onStreamError?.(data));
  const validate = useEffectEvent((data: unknown) => schema?.safeParse(data));

  const retry = useCallback(() => setAttemptKey((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let lastEventId: string | null = null;
    let serverRetryMs: number | null = null;
    let stopped = false;

    const finish = (next: StreamStatus) => {
      if (!stopped) setStatus(next);
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      if (!reconnect) {
        finish("disconnected");
        return;
      }
      if (attempt >= maxRetries) {
        finish("disconnected");
        return;
      }
      const delay = serverRetryMs ?? reconnectDelay(attempt);
      attempt += 1;
      setRetries(attempt);
      setStatus("reconnecting");
      timer = setTimeout(() => void connect(), delay);
    };

    const connect = async () => {
      if (stopped) return;
      const url = new URL(`/api/stream${path}`, window.location.origin);
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (lastEventId) headers["Last-Event-ID"] = lastEventId;
      let init: RequestInit = { method: "GET", headers, signal: controller.signal, cache: "no-store" };
      if (hasBody) {
        headers["Content-Type"] = "application/json";
        init = { ...init, method: "POST", body: JSON.stringify(currentBody()) };
      }

      try {
        const response = await fetch(url, init);
        if (!response.ok || !response.body) {
          if (isFatalStatus(response.status)) finish("disconnected");
          else scheduleReconnect();
          return;
        }
        finish("live");

        const parser = createSseParser((frame) => {
          if (frame.id !== null) lastEventId = frame.id;
          if (frame.retry !== null) serverRetryMs = frame.retry;
          attempt = 0;
          setRetries(0);
          if (frame.event === "stream-error") {
            let payload: unknown = frame.data;
            try {
              payload = JSON.parse(frame.data);
            } catch {
              // keep the raw text
            }
            handleStreamError(payload);
            return;
          }
          let parsed: unknown;
          try {
            parsed = JSON.parse(frame.data);
          } catch {
            console.warn("useEventStream: dropped a frame that is not JSON", { event: frame.event });
            return;
          }
          const checked = validate(parsed);
          if (checked && !checked.success) {
            console.warn("useEventStream: dropped a frame that failed validation", {
              event: frame.event,
            });
            return;
          }
          handleEvent({
            id: frame.id,
            event: frame.event,
            data: (checked ? checked.data : parsed) as T,
          });
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          parser.push(decoder.decode(value, { stream: true }));
        }
        parser.push(decoder.decode());
        parser.flush();
        scheduleReconnect();
      } catch {
        if (stopped || controller.signal.aborted) return;
        scheduleReconnect();
      }
    };

    void connect();

    return () => {
      stopped = true;
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
    // The connection identity: path, body and enabled. Callbacks go through useEffectEvent.
  }, [path, bodyKey, hasBody, enabled, reconnect, maxRetries, attemptKey]);

  return { status: enabled ? current.status : "disconnected", retries: current.retries, retry };
}
