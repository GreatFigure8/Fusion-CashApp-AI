import "server-only";

import { cache } from "react";
import type { z } from "zod";

import { buildApiRequest, errorFromResponse, send } from "@/lib/api/client";
import { apiError, type ApiError } from "@/lib/api/errors";
import {
  cancelOutSchema,
  chatThreadSchema,
  chatToolsSchema,
  type ChatThreadOut,
  type ChatToolsOut,
} from "@/components/common/llm-chat/chat-schemas";
import { err, ok, type Result } from "@/lib/result";

/**
 * Calls an API path the generated OpenAPI types do not describe yet, and checks the JSON with
 * Zod at the boundary. Move to the typed `api` once the chat routes are in schema.d.ts.
 */
export async function chatApi<S extends z.ZodType>(
  method: "get" | "post",
  path: string,
  schema: S,
  options: { body?: unknown; query?: Record<string, string> } = {},
): Promise<Result<z.infer<S>, ApiError>> {
  const prepared = await buildApiRequest(method, path, "application/json", options);
  if (!prepared.ok) return prepared;
  const sent = await send(prepared.value);
  if (!sent.ok) return sent;
  if (!sent.value.ok) return err(await errorFromResponse(sent.value, prepared.value.requestId));
  let json: unknown;
  try {
    json = await sent.value.json();
  } catch {
    json = undefined;
  }
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    return err(
      apiError(
        sent.value.status,
        "invalid_response",
        "The API returned a response in an unexpected shape.",
        prepared.value.requestId,
      ),
    );
  }
  return ok(parsed.data);
}

/** The tool catalog for the signed-in user; one call per request. */
export const getChatTools: () => Promise<Result<ChatToolsOut, ApiError>> = cache(() =>
  chatApi("get", "/chat/tools", chatToolsSchema),
);

export async function getChatThread(id: number): Promise<Result<ChatThreadOut, ApiError>> {
  return chatApi("get", `/chat/threads/${id}`, chatThreadSchema);
}

export async function cancelChatToolCall(callId: string) {
  return chatApi("post", `/chat/tool-calls/${encodeURIComponent(callId)}/cancel`, cancelOutSchema);
}
