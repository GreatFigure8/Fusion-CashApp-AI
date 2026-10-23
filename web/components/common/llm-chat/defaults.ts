import type { PromptKey } from "./chat-schemas";

export const DEFAULT_SUGGESTIONS: Record<PromptKey, readonly string[]> = {
  item: ["Why is this stuck?", "Which receipt fits best?"],
  flow: ["What's driving failures today?"],
};

export const FOOTER_NOTE = "Answers by Claude Haiku 5.5. Check before acting.";

export const TIMEOUT_COPY = "The assistant didn't answer (timeout). Try again";
export const DISCONNECTED_COPY = "The connection dropped before the answer finished.";
