"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { Route } from "next";
import Link from "next/link";
import { CornerDownLeftIcon, SquareIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { MAX_MESSAGE_CHARS } from "./chat-schemas";
import { COPY } from "./defaults";
import { MicButton } from "./mic-button";
import { PromptList } from "./prompt-list";

type ComposerProps = {
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  /** Link to the full-screen assistant, shown at the bottom left when given. */
  fullScreenHref?: string;
  inputId?: string;
  /** Prompt tokens of the last turn, shown as a usage pill when known. */
  inputTokens?: number | null;
};

const CONTEXT_WINDOW_TOKENS = 200_000;

function compactTokens(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

/** The one message box every assistant surface uses (dock, full page, side panel). */
export function Composer({ streaming, onSend, onStop, fullScreenHref, inputId, inputTokens = null }: ComposerProps) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const showPrompts = text.startsWith("/") && !text.includes("\n");

  const submit = () => {
    const value = text.trim();
    if (streaming || value.length === 0 || showPrompts) return;
    onSend(value);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      // Ctrl+Enter inserts a new line at the caret.
      const el = e.currentTarget;
      const start = el.selectionStart;
      const end = el.selectionEnd;
      setText(`${text.slice(0, start)}\n${text.slice(end)}`);
      requestAnimationFrame(() => el.setSelectionRange(start + 1, start + 1));
      return;
    }
    submit();
  };

  const pickPrompt = (prompt: string) => {
    setText(prompt);
    ref.current?.focus();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  return (
    <form
      onSubmit={onSubmit}
      className="relative flex flex-col gap-2 rounded-2xl border border-white/10 bg-background px-4 pb-3 pt-4 transition-colors focus-within:border-white/20"
    >
      {showPrompts ? <PromptList query={text.slice(1)} onPick={pickPrompt} /> : null}
      <Textarea
        ref={ref}
        id={inputId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={streaming}
        maxLength={MAX_MESSAGE_CHARS}
        rows={1}
        placeholder={COPY.placeholder}
        aria-label="Message"
        className="max-h-56 min-h-[3.5rem] w-full resize-none rounded-none border-0 bg-transparent px-1 py-0 text-base shadow-none outline-none focus-visible:border-0 focus-visible:ring-0 disabled:bg-transparent disabled:opacity-100 dark:bg-transparent dark:disabled:bg-transparent md:text-base"
      />
      <div className="flex items-center gap-1.5">
        {fullScreenHref ? (
          <Link href={fullScreenHref as Route} className="shrink-0 text-[12px] text-soft hover:text-foreground">
            {COPY.fullScreen}
          </Link>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          {inputTokens !== null ? (
            <span className="flex h-8 cursor-default items-center rounded-full bg-white/[0.07] px-3 font-mono text-[12.5px] text-muted-foreground">
              {compactTokens(inputTokens)} / {compactTokens(CONTEXT_WINDOW_TOKENS)}
            </span>
          ) : null}
          <MicButton
            disabled={streaming}
            onTranscript={(phrase) => setText((t) => (t.length > 0 ? `${t.trimEnd()} ${phrase}` : phrase))}
          />
          {streaming ? (
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Stop"
              onClick={onStop}
              className="size-9 rounded-lg border-white/30 bg-transparent"
            >
              <SquareIcon className="size-3.5 fill-current" />
            </Button>
          ) : (
            <Button
              type="submit"
              variant="outline"
              size="icon"
              aria-label="Send"
              disabled={text.trim().length === 0 || showPrompts}
              className={cn(
                "size-9 rounded-lg border-white/30 bg-transparent text-foreground hover:bg-white/10",
                "disabled:border-white/15 disabled:text-muted-foreground disabled:opacity-100",
              )}
            >
              <CornerDownLeftIcon />
            </Button>
          )}
        </span>
      </div>
    </form>
  );
}
