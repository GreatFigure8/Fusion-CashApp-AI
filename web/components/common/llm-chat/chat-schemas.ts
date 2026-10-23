import { z } from "zod";

/** The one chat endpoint. The stream proxy allow-lists it; nothing else in web/ may name it. */
export const CHAT_STREAM_PATH = "/chat/stream" as const;

export const MAX_MESSAGE_CHARS = 4000;
export const MAX_REASON_CHARS = 1000;

export const PROMPT_KEYS = ["assistant", "matching", "item", "flow"] as const;
export type PromptKey = (typeof PROMPT_KEYS)[number];

/** Lower-case on the wire (chat-agent-tool-registry). */
export const TOOL_GROUPS = [
  "engine",
  "lab",
  "settings",
  "reports",
  "review",
  "exceptions",
  "fusion_reads",
  "metrics",
] as const;
export type ToolGroup = (typeof TOOL_GROUPS)[number];
const toolGroupSchema = z.enum(TOOL_GROUPS);

/** `id` is "WI-20481" or "20481" for kind "item". The assistant and matching prompts carry no id. */
export type ChatContextRef = { kind: PromptKey; id?: string };

/** The context kinds the API accepts. */
export type WireContext = { kind: "none" | "item" | "flow"; id: string | null };

export function toWireContext(context: ChatContextRef): WireContext {
  if (context.kind === "item" || context.kind === "flow") {
    return { kind: context.kind, id: context.id ?? null };
  }
  return { kind: "none", id: null };
}

// ---- result cards ----------------------------------------------------------------------------

const toneSchema = z.enum(["ok", "accent", "warn", "err", "locked", "muted"]).catch("muted");

export const stateCardSchema = z.object({
  kind: z.literal("state_card"),
  title: z.string(),
  status: z.object({ label: z.string(), tone: toneSchema }),
  stats: z.array(z.object({ label: z.string(), value: z.string() })).default([]),
  history_id: z.string().nullable().default(null),
});

export const replayCardSchema = z.object({
  kind: z.literal("replay_card"),
  candidate_id: z.string(),
  replay_id: z.string(),
  status: z.enum(["RUNNING", "DONE", "FAILED", "STALE"]),
  changed: z.number(),
  newly_matched: z.number(),
  newly_failed: z.number(),
  newly_ambiguous: z.number(),
  currencies: z
    .array(
      z.object({
        currency: z.string(),
        newly_matched: z.string(),
        newly_unmatched: z.string(),
        items: z.number(),
      }),
    )
    .default([]),
  lab_href: z.string(),
});

export const exportCardSchema = z.object({
  kind: z.literal("export_card"),
  filename: z.string(),
  size_bytes: z.number(),
  media_type: z.string().default("text/html"),
  self_contained: z.boolean().default(true),
  preview_href: z.string(),
  download_href: z.string(),
});

export const tableCardSchema = z.object({
  kind: z.literal("table_card"),
  title: z.string(),
  columns: z.array(z.object({ key: z.string(), label: z.string(), numeric: z.boolean().default(false) })),
  rows: z.array(z.record(z.string(), z.union([z.string(), z.number(), z.null()]))),
  total: z.number().nullable().default(null),
  truncated: z.boolean().default(false),
});

export const resultCardSchema = z.discriminatedUnion("kind", [
  stateCardSchema,
  replayCardSchema,
  exportCardSchema,
  tableCardSchema,
]);
export type ResultCard = z.infer<typeof resultCardSchema>;
export type StateCardData = z.infer<typeof stateCardSchema>;
export type ReplayCardData = z.infer<typeof replayCardSchema>;
export type ExportCardData = z.infer<typeof exportCardSchema>;
export type TableCardData = z.infer<typeof tableCardSchema>;

// ---- confirm preview -------------------------------------------------------------------------

export const confirmPreviewSchema = z.object({
  what: z.string(),
  before: z.string(),
  after: z.string(),
  who: z.string(),
  reason_prompt: z.string().default("Why are you making this change?"),
  expected_version: z.number().nullable().default(null),
  details: z.array(z.object({ label: z.string(), value: z.string() })).default([]),
  diff: z
    .array(z.object({ op: z.enum(["-", "+", " "]), text: z.string() }))
    .default([]),
});
export type ConfirmPreview = z.infer<typeof confirmPreviewSchema>;

// ---- SSE events (chat-agent-tool-registry) ---------------------------------------------------

export const textDeltaSchema = z.object({ text: z.string() });

export const toolStartedSchema = z.object({
  call_id: z.string(),
  tool: z.string(),
  group: toolGroupSchema,
  summary: z.string(),
  mutating: z.boolean(),
});

export const toolProgressSchema = z.object({
  call_id: z.string(),
  done: z.number(),
  total: z.number(),
});

export const toolFinishedSchema = z.object({
  call_id: z.string(),
  tool: z.string(),
  duration_ms: z.number(),
  ok: z.boolean(),
  summary: z.string().nullable(),
  result_card: resultCardSchema.nullable(),
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
});

export const confirmRequiredSchema = z.object({
  call_id: z.string(),
  tool: z.string(),
  preview: confirmPreviewSchema,
  expires_at: z.string(),
});

export const chatErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  call_id: z.string().nullable().default(null),
  fatal: z.boolean().default(true),
  thread_id: z.number().nullable().default(null),
});

export const doneSchema = z.object({
  thread_id: z.number(),
  message_id: z.number().optional(),
  stop: z.enum(["end_turn", "awaiting_confirmation", "tool_limit"]).default("end_turn"),
  usage: z.object({
    model_id: z.string(),
    latency_ms: z.number(),
    input_tokens: z.number().nullable(),
    output_tokens: z.number().nullable(),
  }),
});

/** The `stream-error` frame the web stream proxy itself emits. */
export const streamErrorSchema = z.object({ code: z.string(), message: z.string() });

/** Payload schema per SSE event name: exactly the seven registry events. */
export const chatEventSchemas = {
  text_delta: textDeltaSchema,
  tool_started: toolStartedSchema,
  tool_progress: toolProgressSchema,
  tool_finished: toolFinishedSchema,
  confirm_required: confirmRequiredSchema,
  error: chatErrorSchema,
  done: doneSchema,
} as const;
export type ChatEventName = keyof typeof chatEventSchemas;

export type ToolStarted = z.infer<typeof toolStartedSchema>;
export type ToolFinished = z.infer<typeof toolFinishedSchema>;
export type ConfirmRequired = z.infer<typeof confirmRequiredSchema>;
export type ChatDone = z.infer<typeof doneSchema>;
export type ChatError = z.infer<typeof chatErrorSchema>;

// ---- requests --------------------------------------------------------------------------------

export type ChatRequestBody = {
  thread_id: number | null;
  context: WireContext;
  system_prompt_key: PromptKey;
  message: string;
  tool_groups: ToolGroup[] | null;
  upload_ids: string[];
};

export type ConfirmRequestBody = { reason: string; expected_version: number | null };

// ---- reads -----------------------------------------------------------------------------------

export const chatToolsSchema = z.array(
  z.object({
    group: toolGroupSchema,
    allowed: z.boolean(),
    tools: z.array(
      z.object({
        name: z.string(),
        description: z.string(),
        mutating: z.boolean(),
        allowed: z.boolean(),
      }),
    ),
  }),
);
export type ChatToolsOut = z.infer<typeof chatToolsSchema>;

const threadToolSchema = z.object({
  call_id: z.string(),
  tool: z.string(),
  group: toolGroupSchema,
  summary: z.string().nullable().default(null),
  ok: z.boolean().nullable().default(null),
  duration_ms: z.number().nullable().default(null),
  status: z.enum(["done", "failed", "waiting", "cancelled", "expired"]),
  result_card: resultCardSchema.nullable().default(null),
});

export const chatMessageSchema = z.object({
  id: z.number(),
  seq: z.number().optional(),
  role: z.enum(["user", "assistant"]),
  text: z.string(),
  tools: z.array(threadToolSchema).default([]),
});
export type ChatMessageOut = z.infer<typeof chatMessageSchema>;

export const chatThreadSchema = z.object({
  id: z.number(),
  prompt_key: z.enum(PROMPT_KEYS),
  title: z.string().nullable().default(null),
  messages: z.array(chatMessageSchema),
  pending: z
    .object({
      call_id: z.string(),
      tool: z.string(),
      preview: confirmPreviewSchema,
      expires_at: z.string(),
    })
    .nullable()
    .default(null),
});
export type ChatThreadOut = z.infer<typeof chatThreadSchema>;
export type PendingConfirm = NonNullable<ChatThreadOut["pending"]>;

export const cancelOutSchema = z.object({ call_id: z.string(), status: z.string() });

export const uploadStageSchema = z.object({ upload_ids: z.array(z.string()) });
