import {
  MAX_MESSAGE_CHARS,
  MAX_TURNS,
  type ChatActionArgs,
  type ChatContextRef,
  type ChatMessage,
  type ChatRequestBody,
  type PromptKey,
} from "./chat-schemas";

export type ChatPhase = "idle" | "streaming" | "done" | "error" | "disconnected" | "stopped";

export type ChatState = {
  messages: readonly ChatMessage[];
  phase: ChatPhase;
  /** The body of the request in flight (or last sent). Null before the first send. */
  request: ChatRequestBody | null;
  error: { code: string; message: string } | null;
  nextId: number;
};

export const initialChatState: ChatState = {
  messages: [],
  phase: "idle",
  request: null,
  error: null,
  nextId: 1,
};

export type ChatReducerAction =
  | {
      type: "send";
      text: string;
      context: ChatContextRef;
      systemPromptKey: PromptKey;
      allowedActions: readonly string[];
    }
  | { type: "token"; text: string }
  | { type: "action"; id: string; label: string; args: ChatActionArgs }
  | { type: "done" }
  | { type: "stream-error"; code: string; message: string }
  | { type: "disconnected" }
  | { type: "stop" }
  | { type: "retry" };

function newMessage(id: number, role: ChatMessage["role"], content: string): ChatMessage {
  return { id, role, content, actions: [], stopped: false };
}

/** Completed turns only: no empty drafts. Capped to what the API accepts. */
function toBodyMessages(messages: readonly ChatMessage[]): ChatRequestBody["messages"] {
  return messages
    .filter((m) => m.content.length > 0)
    .slice(-MAX_TURNS)
    .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_MESSAGE_CHARS) }));
}

function updateDraft(state: ChatState, change: (draft: ChatMessage) => ChatMessage): ChatState {
  const last = state.messages[state.messages.length - 1];
  if (!last || last.role !== "assistant") return state;
  return { ...state, messages: [...state.messages.slice(0, -1), change(last)] };
}

/** True while an answer is being produced or could still be resumed by Retry. */
function hasDraft(state: ChatState): boolean {
  return state.messages[state.messages.length - 1]?.role === "assistant";
}

export function chatReducer(state: ChatState, action: ChatReducerAction): ChatState {
  switch (action.type) {
    case "send": {
      const text = action.text.trim();
      if (text.length === 0 || state.phase === "streaming") return state;
      const user = newMessage(state.nextId, "user", text.slice(0, MAX_MESSAGE_CHARS));
      const draft = newMessage(state.nextId + 1, "assistant", "");
      const completed = state.messages.filter((m) => m.content.length > 0);
      return {
        messages: [...state.messages, user, draft],
        phase: "streaming",
        request: {
          context: action.context,
          system_prompt_key: action.systemPromptKey,
          messages: toBodyMessages([...completed, user]),
          allowed_actions: [...action.allowedActions],
        },
        error: null,
        nextId: state.nextId + 2,
      };
    }
    case "token":
      if (state.phase !== "streaming") return state;
      return updateDraft(state, (d) => ({ ...d, content: d.content + action.text }));
    case "action":
      if (state.phase !== "streaming") return state;
      return updateDraft(state, (d) =>
        d.actions.some((a) => a.id === action.id)
          ? d
          : { ...d, actions: [...d.actions, { id: action.id, label: action.label, args: action.args }] },
      );
    case "done":
      return state.phase === "streaming" ? { ...state, phase: "done" } : state;
    case "stream-error":
      if (state.phase !== "streaming") return state;
      return { ...state, phase: "error", error: { code: action.code, message: action.message } };
    case "disconnected":
      // Only a stream that ended without `done` or `stream-error` is a lost connection.
      return state.phase === "streaming" ? { ...state, phase: "disconnected" } : state;
    case "stop": {
      if (state.phase !== "streaming") return state;
      const stopped = updateDraft(state, (d) => ({ ...d, stopped: true }));
      return { ...stopped, phase: "stopped" };
    }
    case "retry": {
      if ((state.phase !== "error" && state.phase !== "disconnected") || !hasDraft(state)) {
        return state;
      }
      // Drop the failed draft and start a fresh one for the same request body.
      const kept = state.messages.slice(0, -1);
      const draft = newMessage(state.nextId, "assistant", "");
      return {
        ...state,
        messages: [...kept, draft],
        phase: "streaming",
        error: null,
        nextId: state.nextId + 1,
      };
    }
  }
}
