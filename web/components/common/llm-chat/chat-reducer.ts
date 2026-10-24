import {
  MAX_MESSAGE_CHARS,
  type ChatContextRef,
  type ChatDone,
  type ChatError,
  type ChatMessageOut,
  type ChatRequestBody,
  type ConfirmPreview,
  type ConfirmRequestBody,
  type PendingConfirm,
  type PromptKey,
  type ResultCard,
  type ToolFinished,
  type ToolGroup,
  type ToolStarted,
  toWireContext,
} from "./chat-schemas";

export type ChatPhase =
  | "idle"
  | "streaming"
  | "awaiting_confirm"
  | "done"
  | "error"
  | "disconnected"
  | "stopped";

export type ToolStatus = "running" | "waiting" | "ok" | "failed" | "cancelled";

export type ToolRow = {
  callId: string;
  tool: string;
  group: ToolGroup;
  summary: string;
  mutating: boolean;
  status: ToolStatus;
  done: number | null;
  total: number | null;
  durationMs: number | null;
  error: { code: string; message: string } | null;
};

export type ConfirmDecision = "pending" | "sending" | "confirmed" | "cancelled";

export type MessagePart =
  | { kind: "text"; text: string }
  | { kind: "tool"; row: ToolRow }
  | {
      kind: "confirm";
      callId: string;
      tool: string;
      preview: ConfirmPreview;
      expiresAt: string;
      decision: ConfirmDecision;
    }
  | { kind: "card"; callId: string; card: ResultCard };

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  parts: readonly MessagePart[];
  /** The person pressed Stop: the text is partial. */
  stopped: boolean;
};

export type ChatRequest =
  | { kind: "turn"; body: ChatRequestBody }
  | { kind: "confirm"; callId: string; body: ConfirmRequestBody };

export type ChatState = {
  messages: readonly ChatMessage[];
  phase: ChatPhase;
  threadId: number | null;
  /** The request in flight (or last sent). Null before the first send. */
  request: ChatRequest | null;
  error: { code: string; message: string } | null;
  /** From the last `done`; shown in the header. */
  modelId: string | null;
  /** Prompt tokens of the last turn, shown beside the composer. Null before the first answer. */
  inputTokens: number | null;
  nextId: number;
};

export const initialChatState: ChatState = {
  messages: [],
  phase: "idle",
  threadId: null,
  request: null,
  error: null,
  modelId: null,
  inputTokens: null,
  nextId: 1,
};

export type ChatReducerAction =
  | {
      type: "send";
      text: string;
      context: ChatContextRef;
      systemPromptKey: PromptKey;
      toolGroups: readonly ToolGroup[] | null;
      uploadIds: readonly string[];
    }
  | { type: "text_delta"; text: string }
  | { type: "tool_started"; event: ToolStarted }
  | { type: "tool_progress"; callId: string; done: number; total: number }
  | { type: "tool_finished"; event: ToolFinished }
  | {
      type: "confirm_required";
      callId: string;
      tool: string;
      preview: ConfirmPreview;
      expiresAt: string;
    }
  | { type: "error"; error: ChatError }
  | { type: "done"; event: ChatDone }
  | { type: "stream-error"; code: string; message: string }
  | { type: "disconnected" }
  | { type: "stop" }
  | { type: "retry" }
  | { type: "confirm-sent"; callId: string; reason: string }
  | { type: "cancel-sent"; callId: string }
  | { type: "hydrate"; threadId: number; messages: readonly ChatMessageOut[]; pending: PendingConfirm | null };

function newMessage(id: number, role: ChatMessage["role"], parts: readonly MessagePart[]): ChatMessage {
  return { id, role, parts, stopped: false };
}

function updateDraft(state: ChatState, change: (draft: ChatMessage) => ChatMessage): ChatState {
  const last = state.messages[state.messages.length - 1];
  if (!last || last.role !== "assistant") return state;
  return { ...state, messages: [...state.messages.slice(0, -1), change(last)] };
}

/** Appends text to the trailing text part, or starts one. */
function appendText(parts: readonly MessagePart[], text: string): readonly MessagePart[] {
  const tail = parts[parts.length - 1];
  if (tail && tail.kind === "text") {
    return [...parts.slice(0, -1), { kind: "text", text: tail.text + text }];
  }
  return [...parts, { kind: "text", text }];
}

function findToolRow(state: ChatState, callId: string): boolean {
  return state.messages.some((m) => m.parts.some((p) => p.kind === "tool" && p.row.callId === callId));
}

/** Maps every tool part with this call id, wherever it sits in the thread. */
function mapParts(
  state: ChatState,
  map: (part: MessagePart) => MessagePart,
): ChatState {
  return {
    ...state,
    messages: state.messages.map((m) => ({ ...m, parts: m.parts.map(map) })),
  };
}

function patchRow(state: ChatState, callId: string, patch: Partial<ToolRow>): ChatState {
  return mapParts(state, (p) =>
    p.kind === "tool" && p.row.callId === callId ? { ...p, row: { ...p.row, ...patch } } : p,
  );
}

function patchConfirm(state: ChatState, callId: string, decision: ConfirmDecision): ChatState {
  return mapParts(state, (p) =>
    p.kind === "confirm" && p.callId === callId ? { ...p, decision } : p,
  );
}

function rowFromStarted(e: ToolStarted): ToolRow {
  return {
    callId: e.call_id,
    tool: e.tool,
    group: e.group,
    summary: e.summary,
    mutating: e.mutating,
    status: "running",
    done: null,
    total: null,
    durationMs: null,
    error: null,
  };
}

function messageFromThread(id: number, m: ChatMessageOut): ChatMessage {
  const parts: MessagePart[] = [];
  for (const t of m.tools) {
    const status: ToolStatus =
      t.status === "waiting"
        ? "waiting"
        : t.status === "cancelled" || t.status === "expired"
          ? "cancelled"
          : t.status === "failed" || t.ok === false
            ? "failed"
            : "ok";
    parts.push({
      kind: "tool",
      row: {
        callId: t.call_id,
        tool: t.tool,
        group: t.group,
        summary: t.summary ?? "",
        mutating: false,
        status,
        done: null,
        total: null,
        durationMs: t.duration_ms,
        error: null,
      },
    });
    if (t.result_card) parts.push({ kind: "card", callId: t.call_id, card: t.result_card });
  }
  if (m.text.length > 0) parts.push({ kind: "text", text: m.text });
  return newMessage(id, m.role, parts);
}

export function hydratedState(
  threadId: number,
  messages: readonly ChatMessageOut[],
  pending: PendingConfirm | null,
): ChatState {
  const mapped = messages.map((m, i) => messageFromThread(i + 1, m));
  let nextId = mapped.length + 1;
  let phase: ChatPhase = mapped.length > 0 ? "done" : "idle";
  let all = mapped;
  if (pending) {
    const confirm: ChatMessage = newMessage(nextId, "assistant", [
      {
        kind: "confirm",
        callId: pending.call_id,
        tool: pending.tool,
        preview: pending.preview,
        expiresAt: pending.expires_at,
        decision: "pending",
      },
    ]);
    nextId += 1;
    all = [...mapped, confirm];
    phase = "awaiting_confirm";
  }
  return { ...initialChatState, messages: all, phase, threadId, nextId };
}

export function chatReducer(state: ChatState, action: ChatReducerAction): ChatState {
  switch (action.type) {
    case "hydrate":
      return hydratedState(action.threadId, action.messages, action.pending);
    case "send": {
      const text = action.text.trim();
      if (text.length === 0 || state.phase === "streaming") return state;
      const clipped = text.slice(0, MAX_MESSAGE_CHARS);
      const user = newMessage(state.nextId, "user", [{ kind: "text", text: clipped }]);
      const draft = newMessage(state.nextId + 1, "assistant", []);
      return {
        ...state,
        messages: [...state.messages, user, draft],
        phase: "streaming",
        request: {
          kind: "turn",
          body: {
            thread_id: state.threadId,
            context: toWireContext(action.context),
            system_prompt_key: action.systemPromptKey,
            message: clipped,
            tool_groups: action.toolGroups ? [...action.toolGroups] : null,
            upload_ids: [...action.uploadIds],
          },
        },
        error: null,
        nextId: state.nextId + 2,
      };
    }
    case "text_delta":
      if (state.phase !== "streaming") return state;
      return updateDraft(state, (d) => ({ ...d, parts: appendText(d.parts, action.text) }));
    case "tool_started": {
      if (state.phase !== "streaming") return state;
      if (findToolRow(state, action.event.call_id)) {
        return patchRow(state, action.event.call_id, { status: "running" });
      }
      return updateDraft(state, (d) => ({
        ...d,
        parts: [...d.parts, { kind: "tool", row: rowFromStarted(action.event) }],
      }));
    }
    case "tool_progress":
      return patchRow(state, action.callId, { done: action.done, total: action.total });
    case "tool_finished": {
      const e = action.event;
      const change: Partial<ToolRow> = {
        status: e.ok ? "ok" : "failed",
        durationMs: e.duration_ms,
        error: e.error,
      };
      if (e.summary !== null) change.summary = e.summary;
      const patched = patchRow(state, e.call_id, change);
      const card = e.result_card;
      if (!card) return patched;
      return updateDraft(patched, (d) => ({
        ...d,
        parts: [...d.parts, { kind: "card", callId: e.call_id, card }],
      }));
    }
    case "confirm_required": {
      if (state.phase !== "streaming") return state;
      const waiting = patchRow(state, action.callId, { status: "waiting" });
      return updateDraft(waiting, (d) => ({
        ...d,
        parts: [
          ...d.parts,
          {
            kind: "confirm",
            callId: action.callId,
            tool: action.tool,
            preview: action.preview,
            expiresAt: action.expiresAt,
            decision: "pending",
          },
        ],
      }));
    }
    case "done": {
      if (state.phase !== "streaming") return state;
      const settled =
        state.request?.kind === "confirm"
          ? patchConfirm(state, state.request.callId, "confirmed")
          : state;
      return {
        ...settled,
        phase: action.event.stop === "awaiting_confirmation" ? "awaiting_confirm" : "done",
        threadId: action.event.thread_id,
        modelId: action.event.usage.model_id,
        inputTokens: action.event.usage.input_tokens,
      };
    }
    case "error": {
      if (state.phase !== "streaming") return state;
      const threadId = action.error.thread_id ?? state.threadId;
      const failedRow = action.error.call_id
        ? patchRow(state, action.error.call_id, {
            status: "failed",
            error: { code: action.error.code, message: action.error.message },
          })
        : state;
      return {
        ...failedRow,
        phase: "error",
        threadId,
        error: { code: action.error.code, message: action.error.message },
      };
    }
    case "stream-error":
      if (state.phase !== "streaming") return state;
      return { ...state, phase: "error", error: { code: action.code, message: action.message } };
    case "disconnected":
      // Only a stream that ended without `done` or an error is a lost connection.
      return state.phase === "streaming" ? { ...state, phase: "disconnected" } : state;
    case "stop": {
      if (state.phase !== "streaming") return state;
      const stopped = updateDraft(state, (d) => ({ ...d, stopped: true }));
      return { ...stopped, phase: "stopped" };
    }
    case "retry": {
      if (state.phase !== "error" && state.phase !== "disconnected") return state;
      if (!state.request) return state;
      const kept = state.messages.slice(0, -1);
      const draft = newMessage(state.nextId, "assistant", []);
      return {
        ...state,
        messages: [...kept, draft],
        phase: "streaming",
        error: null,
        nextId: state.nextId + 1,
      };
    }
    case "confirm-sent": {
      if (state.phase === "streaming") return state;
      const row = patchConfirm(state, action.callId, "sending");
      const confirm = findConfirm(state, action.callId);
      const draft = newMessage(row.nextId, "assistant", []);
      return {
        ...row,
        messages: [...row.messages, draft],
        phase: "streaming",
        request: {
          kind: "confirm",
          callId: action.callId,
          body: {
            reason: action.reason.trim().slice(0, 1000),
            expected_version: confirm?.preview.expected_version ?? null,
          },
        },
        error: null,
        nextId: row.nextId + 1,
      };
    }
    case "cancel-sent": {
      const decided = patchConfirm(state, action.callId, "cancelled");
      const row = patchRow(decided, action.callId, { status: "cancelled" });
      return row.phase === "awaiting_confirm" ? { ...row, phase: "done" } : row;
    }
  }
}

function findConfirm(state: ChatState, callId: string) {
  for (const m of state.messages) {
    for (const p of m.parts) {
      if (p.kind === "confirm" && p.callId === callId) return p;
    }
  }
  return undefined;
}

/** Plain text of a message: used by the stream's visible tail check. */
export function messageText(m: ChatMessage): string {
  return m.parts.map((p) => (p.kind === "text" ? p.text : "")).join("");
}
