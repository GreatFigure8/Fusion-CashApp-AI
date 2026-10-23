import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

import type { SseStep } from "./sse-mock";

/**
 * A programmable HTTP and SSE stand-in for the Python API, for Playwright. The Next server calls
 * the API from the server side, so browser-level request routing cannot intercept those calls;
 * a real listener on `API_BASE_URL` can. Specs program it through the helpers below, which talk to
 * the server's `/__mock/*` control endpoints.
 */

export const MOCK_API_PORT: number = Number(process.env.MOCK_API_PORT ?? 3199);

type MockResponse = {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  delayMs?: number;
};

export type RecordedRequest = { method: string; path: string; body: string };

const routes = new Map<string, MockResponse>();
const streams = new Map<string, readonly SseStep[]>();
let recorded: RecordedRequest[] = [];

const key = (method: string, path: string) => `${method.toUpperCase()} ${path}`;

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

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

async function playStream(response: ServerResponse, steps: readonly SseStep[]): Promise<void> {
  response.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  for (const step of steps) {
    if (response.destroyed) return;
    if ("delayMs" in step) {
      await new Promise((resolve) => setTimeout(resolve, step.delayMs));
    } else if ("close" in step) {
      response.end();
      return;
    } else if ("error" in step) {
      response.destroy();
      return;
    } else {
      const text = encode(step);
      if (text !== null) response.write(text);
    }
  }
  // Stay open like a real stream until the client goes away.
}

function json(response: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  const payload = body === undefined ? "" : JSON.stringify(body);
  response.writeHead(status, { "Content-Type": "application/json", ...headers });
  response.end(payload);
}

async function control(path: string, body: string, response: ServerResponse): Promise<void> {
  const data: unknown = body ? JSON.parse(body) : {};
  if (path === "/__mock/route") {
    const { method, path: target, response: reply } = data as {
      method: string;
      path: string;
      response: MockResponse;
    };
    routes.set(key(method, target), reply);
  } else if (path === "/__mock/stream") {
    const { path: target, steps } = data as { path: string; steps: SseStep[] };
    streams.set(target, steps);
  } else if (path === "/__mock/reset") {
    routes.clear();
    streams.clear();
    recorded = [];
  } else if (path === "/__mock/requests") {
    json(response, 200, recorded);
    return;
  }
  json(response, 200, { ok: true });
}

async function handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const url = new URL(request.url ?? "/", "http://mock.local");
  const method = request.method ?? "GET";
  const body = await readBody(request);

  if (url.pathname.startsWith("/__mock/")) {
    await control(url.pathname, body, response);
    return;
  }
  recorded.push({ method, path: url.pathname, body });

  const stream = streams.get(url.pathname);
  if (stream && method === "GET") {
    await playStream(response, stream);
    return;
  }
  const reply = routes.get(key(method, url.pathname));
  if (!reply) {
    json(response, 404, {
      error: { code: "not_found", message: "No mock programmed", request_id: "mock", details: [] },
    });
    return;
  }
  if (reply.delayMs) await new Promise((resolve) => setTimeout(resolve, reply.delayMs));
  json(response, reply.status ?? 200, reply.body, reply.headers);
}

export function startMockApiServer(port: number = MOCK_API_PORT): Promise<{ close(): Promise<void> }> {
  return new Promise((resolve, reject) => {
    const server: Server = createServer((request, response) => {
      handle(request, response).catch(() => {
        if (!response.headersSent) json(response, 500, { error: { code: "mock_error" } });
        else response.destroy();
      });
    });
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () =>
      resolve({
        close: () =>
          new Promise<void>((done) => {
            server.closeAllConnections();
            server.close(() => done());
          }),
      }),
    );
  });
}

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`http://127.0.0.1:${MOCK_API_PORT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Program the reply for `METHOD path` (for example `GET /flow/summary`). */
export async function setMockRoute(method: string, path: string, response: MockResponse): Promise<void> {
  await post("/__mock/route", { method, path, response });
}

/** Program an SSE stream for `GET path`; the steps play in order, then the stream stays open. */
export async function setMockStream(path: string, steps: readonly SseStep[]): Promise<void> {
  await post("/__mock/stream", { path, steps });
}

export async function resetMock(): Promise<void> {
  await post("/__mock/reset", {});
}

/** Every non-control request the mock has received since the last reset. */
export async function getMockRequests(): Promise<RecordedRequest[]> {
  const response = await post("/__mock/requests", {});
  return (await response.json()) as RecordedRequest[];
}
