"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useEventStream, type StreamEvent, type StreamStatus } from "@/lib/api/use-event-stream";
import type { Schemas } from "@/lib/api/types";
import { flowStreamDataSchema, type FlowStreamData } from "@/lib/flow/stream-schemas";

type ItemChanged = Schemas["ItemChangedOut"];
type FlowSummary = Schemas["FlowSummaryOut"];

type FlowStreamValue = {
  status: StreamStatus;
  retries: number;
  retry: () => void;
  summary: FlowSummary | null;
  subscribeItemChanged: (cb: (e: ItemChanged) => void) => () => void;
};

const FlowStreamContext = createContext<FlowStreamValue | null>(null);

/** The only `/flow/stream` consumer in `web/`: one connection per tab, shared through context. */
export function FlowStreamProvider({ children }: { children: ReactNode }) {
  const [summary, setSummary] = useState<FlowSummary | null>(null);
  const subscribers = useRef(new Set<(e: ItemChanged) => void>());

  const onEvent = useCallback((frame: StreamEvent<FlowStreamData>) => {
    if (frame.event === "summary") {
      setSummary(frame.data as FlowSummary);
    } else if (frame.event === "item_changed") {
      for (const callback of subscribers.current) callback(frame.data as ItemChanged);
    }
  }, []);

  const { status, retries, retry } = useEventStream<FlowStreamData>("/flow/stream", {
    schema: flowStreamDataSchema,
    onEvent,
  });

  const subscribeItemChanged = useCallback((callback: (e: ItemChanged) => void) => {
    subscribers.current.add(callback);
    return () => {
      subscribers.current.delete(callback);
    };
  }, []);

  const value = useMemo<FlowStreamValue>(
    () => ({ status, retries, retry, summary, subscribeItemChanged }),
    [status, retries, retry, summary, subscribeItemChanged],
  );
  return <FlowStreamContext.Provider value={value}>{children}</FlowStreamContext.Provider>;
}

export function useFlowStream(): FlowStreamValue {
  const value = useContext(FlowStreamContext);
  if (value === null) throw new Error("useFlowStream must be used inside FlowStreamProvider");
  return value;
}
