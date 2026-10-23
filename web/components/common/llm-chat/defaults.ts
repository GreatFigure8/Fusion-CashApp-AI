import type { PromptKey, ToolGroup } from "./chat-schemas";

/** Dock chips by route; the longest matching prefix wins. */
export const ROUTE_CHIPS: Readonly<Record<string, readonly string[]>> = {
  "/": ["Show live progress", "Where are items waiting longest?", "Submit failed receipts"],
  "/flow": ["Where are items waiting longest?", "Pause apply until 15:00", "Show live progress"],
  "/exceptions": ["Work my oldest exception", "Which auto-fix fails most?", "Submit failed receipts"],
  "/reports": ["Export this week's report", "Show live progress", "Which auto-fix fails most?"],
  "/config": ["What changed in settings this week?", "Show live progress"],
  "/lab": [
    "Try a ±3 day window for INR only",
    "Why do INR items go ambiguous?",
    "Replay my last candidate on 7 days",
  ],
  "/review": ["Submit failed receipts", "Work my oldest exception"],
  "/items": ["Why is this stuck?", "Which receipt fits best?"],
};

export function chipsForRoute(pathname: string): readonly string[] {
  let best = "/";
  for (const prefix of Object.keys(ROUTE_CHIPS)) {
    const matches = pathname === prefix || pathname.startsWith(`${prefix}/`);
    if (matches && prefix.length > best.length) best = prefix;
  }
  return ROUTE_CHIPS[best] ?? [];
}

/** Chips above the full-screen composer. */
export const FULL_CHIPS: readonly string[] = [
  "Where is time lost between stations?",
  "Which auto-fix fails most?",
  "Is the Cohere cluster oversized?",
  "Work my oldest exception",
];

/** The empty-state welcome. */
export const WELCOME_TITLE = "What should CashApp do?";
export const WELCOME_CHIPS: readonly string[] = [
  "Show live progress",
  "Pause a station",
  "Submit failed receipts",
];

/** Chips for embedded chats, by prompt key. */
export const PROMPT_CHIPS: Readonly<Record<PromptKey, readonly string[]>> = {
  assistant: WELCOME_CHIPS,
  matching: ["What does this candidate change?", "Replay the candidate"],
  item: ["Why is this stuck?", "Which receipt fits best?"],
  flow: ["What's driving failures today?"],
};

/** The `/` prompt list. */
export const PROMPT_LIST: readonly string[] = [
  "Show live progress",
  "Pause apply until 15:00",
  "Resume apply",
  "Export this week's report",
  "Submit failed receipts",
  "Work my oldest exception",
  "Where are items waiting longest?",
  "Is the Cohere cluster oversized?",
];

export const TOOL_GROUP_LABELS: Readonly<Record<ToolGroup, string>> = {
  engine: "Engine",
  lab: "Lab",
  settings: "Settings",
  reports: "Reports",
  review: "Review",
  exceptions: "Exceptions",
  fusion_reads: "Fusion reads",
  metrics: "Progress",
};

/** The "Your tools" rows: what each group lets the assistant do. */
export const TOOL_GROUP_ABILITIES: Readonly<Record<ToolGroup, string>> = {
  engine: "Engine control",
  settings: "Change settings",
  lab: "Lab replay and promote",
  exceptions: "Work exceptions",
  review: "Submit receipt images",
  reports: "Export reports",
  fusion_reads: "Fusion reads",
  metrics: "Progress",
};

export const MODEL_DISPLAY: Readonly<Record<string, string>> = {
  "claude-haiku-5-5": "Haiku 5.5",
  "claude-opus-5-5": "Opus 5.5",
};
export const DEFAULT_MODEL_LABEL = "Haiku 5.5";

export function modelLabel(modelId: string | null): string {
  if (modelId === null) return DEFAULT_MODEL_LABEL;
  return MODEL_DISPLAY[modelId] ?? modelId;
}

export const DEFAULT_UPLOADS = {
  maxBytes: 5 * 1024 * 1024,
  maxFiles: 10,
  accept: ["image/png", "image/jpeg", "image/webp", "application/pdf"],
} as const;

export const COPY = {
  placeholder: "Ask or tell CashApp to do something…",
  fullPlaceholder: "Ask, or tell CashApp what to do. / for prompts, + for images.",
  dockHint: "Acts with your permissions · every change asks you to confirm · ⌘K",
  fullHint: "Changes run only after you confirm",
  footnote: "The assistant can never do more than your role allows.",
  dockLabel: "ASSISTANT",
  fullScreen: "Full screen",
  expired: "This change expired. Ask again.",
  nothingChanged: "Nothing changed.",
  waiting: "waiting for your confirmation",
  deniedBody: "The assistant can draft the change for an administrator to apply.",
  timeout: "The assistant didn't answer (timeout). Try again",
  disconnected: "The connection dropped before the answer finished.",
} as const;
