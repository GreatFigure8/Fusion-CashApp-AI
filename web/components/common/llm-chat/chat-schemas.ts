import { z } from "zod";

import type { ApiError } from "@/lib/api/errors";
import type { Result } from "@/lib/result";

/** The one chat endpoint. s31's stream proxy allow-lists it; nothing else may name it. */
export const CHAT_STREAM_PATH = "/chat/stream" as const;

export const MAX_MESSAGE_CHARS = 4000;
export const MAX_TURNS = 20;

export type PromptKey = "item" | "flow";

/** `id` is "WI-20481" or "20481" for kind "item". */
export type ChatContextRef = { kind: PromptKey; id?: string };

export type ChatActionSpec = { id: string; label: string; confirm?: string };

export type ChatActionArgs = Readonly<Record<string, string | number | boolean | null>>;

/** A server action passed from a Server Component. It returns a Result; it must not throw. */
export type ChatActionHandler = (id: string, args: ChatActionArgs) => Promise<Result<unknown, ApiError>>;

export type ChatMessageRole = "user" | "assistant";

export type ProposedAction = { id: string; label: string; args: ChatActionArgs };

export type ChatMessage = {
  id: number;
  role: ChatMessageRole;
  content: string;
  actions: readonly ProposedAction[];
  /** The person pressed Stop: the text is partial. */
  stopped: boolean;
};

/** The request body the API validates (see the OpenAPI schema for `/chat/stream`). */
export type ChatRequestBody = {
  context: ChatContextRef;
  system_prompt_key: PromptKey;
  messages: { role: ChatMessageRole; content: string }[];
  allowed_actions: string[];
};

const argValueSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);

export const tokenDataSchema = z.object({ text: z.string() });

export const actionDataSchema = z.object({
  id: z.string(),
  label: z.string(),
  args: z.record(z.string(), argValueSchema),
});

export const doneDataSchema = z.object({
  usage: z.object({
    model_id: z.string(),
    latency_ms: z.number(),
    input_tokens: z.number().nullable(),
    output_tokens: z.number().nullable(),
  }),
});

export const streamErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
});

/** Payload schema per SSE event name. */
export const chatEventSchemas = {
  token: tokenDataSchema,
  action: actionDataSchema,
  done: doneDataSchema,
  "stream-error": streamErrorSchema,
} as const;

/** Any one data frame (not `stream-error`, which the stream hook routes separately). */
export const chatFrameSchema = z.union([tokenDataSchema, actionDataSchema, doneDataSchema]);
export type ChatFrame = z.infer<typeof chatFrameSchema>;

export type ChatStreamError = z.infer<typeof streamErrorSchema>;
