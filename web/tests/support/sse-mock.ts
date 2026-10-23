import { http } from "msw";

import type { StreamPath } from "@/lib/api/stream-paths";

import { apiServer, TEST_API_BASE_URL } from "./api-mock";

export type SseStep =
  | { event?: string; id?: string; data: unknown }
  | { comment: string }
  | { retry: number }
  | { delayMs: number }
  | { close: true }
  | { error: true };

type StreamOptions = { method?: "get" | "post"; status?: number };

const seen: Request[] = [];

function encode(step: SseStep): string | null {
  if ("data" in step) {
    const lines: string[] = [];
    if (step.id !== undefined) lines.push(`id: ${step.id}`);
    if (step.event !== undefined) lines.push(`event: ${step.event}`);
    lines.push(`data: ${JSON.stringify(step.data)}`);
    return `${lines.join("\n")}\n\n`;
  }
  if ("comment" in step) return `: ${step.comment}\n\n`;
  if ("retry" in step) return `retry: ${step.retry}\n\n`;
  return null;
}

/** A text/event-stream response that plays the steps in order. */
export function sseResponse(steps: readonly SseStep[], init: ResponseInit = {}): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const step of steps) {
        if ("delayMs" in step) {
          await new Promise((resolve) => setTimeout(resolve, step.delayMs));
        } else if ("close" in step) {
          controller.close();
          return;
        } else if ("error" in step) {
          controller.error(new Error("connection dropped"));
          return;
        } else {
          const text = encode(step);
          if (text !== null) controller.enqueue(encoder.encode(text));
        }
      }
      controller.close();
    },
  });
  return new Response(stream, {
    ...init,
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", ...init.headers },
  });
}

function isSequence(
  steps: readonly SseStep[] | readonly (readonly SseStep[])[],
): steps is readonly (readonly SseStep[])[] {
  return steps.length > 0 && Array.isArray(steps[0]);
}

function register(
  url: string,
  steps: readonly SseStep[] | readonly (readonly SseStep[])[],
  opts: StreamOptions,
): void {
  const connections: readonly (readonly SseStep[])[] = isSequence(steps) ? steps : [steps];
  let index = 0;
  apiServer.use(
    http[opts.method ?? "get"](url, ({ request }) => {
      seen.push(request.clone());
      const plan = connections[Math.min(index, connections.length - 1)] ?? [];
      index += 1;
      if (opts.status !== undefined && opts.status >= 400) {
        return new Response(null, { status: opts.status });
      }
      return sseResponse(plan, { status: opts.status ?? 200 });
    }),
  );
}

/** The web origin's stream proxy (`/api/stream<path>`), as seen by `useEventStream`. */
export function mockStream(
  path: StreamPath,
  steps: readonly SseStep[] | readonly (readonly SseStep[])[],
  opts: StreamOptions = {},
): void {
  const origin = typeof location === "undefined" ? "http://localhost:3000" : location.origin;
  register(`${origin}/api/stream${path}`, steps, opts);
}

/** The Python API's stream endpoint, as seen by the server-side proxy. */
export function mockApiStream(
  path: StreamPath,
  steps: readonly SseStep[],
  opts: StreamOptions = {},
): void {
  register(`${TEST_API_BASE_URL}${path}`, steps, opts);
}

/** Requests seen by `mockStream` and `mockApiStream`, oldest first. */
export function streamRequests(): Request[] {
  return seen;
}
