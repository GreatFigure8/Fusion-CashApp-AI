"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { Route } from "next";
import Link from "next/link";
import { ArrowUpIcon, SquareIcon } from "lucide-react";

import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { Attach, type StagedUpload, type UploadLimits } from "./attach";
import { MAX_MESSAGE_CHARS } from "./chat-schemas";
import { COPY } from "./defaults";
import { PromptList } from "./prompt-list";

export type ComposerForm = "dock" | "full" | "compact";

type ComposerProps = {
  form: ComposerForm;
  streaming: boolean;
  onSend: (text: string, uploadIds: readonly string[]) => void;
  onStop: () => void;
  /** Labels of the tool groups this chat may use; shown as one muted pill. */
  toolLabels?: readonly string[];
  /** Dock only: the full-screen link target. */
  fullScreenHref?: string;
  inputId?: string;
  uploadLimits?: UploadLimits;
};

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-line bg-surface-3 px-1 font-mono text-[10.75px]">{children}</kbd>
  );
}

function HintRow({ form }: { form: ComposerForm }) {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.75px] text-soft">
      <span>
        <Kbd>↵</Kbd> Send
      </span>
      {form === "full" ? (
        <span>
          <Kbd>Ctrl+↵</Kbd> New line
        </span>
      ) : null}
      <span>
        <Kbd>/</Kbd> Prompts
      </span>
      {form === "full" ? (
        <span>
          <Kbd>+</Kbd> Images
        </span>
      ) : null}
      {form === "full" ? <span className="ml-auto">{COPY.fullHint}</span> : null}
    </p>
  );
}

export function Composer({
  form,
  streaming,
  onSend,
  onStop,
  toolLabels = [],
  fullScreenHref,
  inputId,
  uploadLimits,
}: ComposerProps) {
  const [text, setText] = useState("");
  const [staged, setStaged] = useState<readonly StagedUpload[]>([]);
  const ref = useRef<HTMLTextAreaElement>(null);
  const showPrompts = text.startsWith("/") && !text.includes("\n");

  const submit = () => {
    const value = text.trim();
    if (streaming || value.length === 0 || showPrompts) return;
    onSend(value, staged.map((s) => s.id));
    setText("");
    setStaged([]);
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

  const send = streaming ? (
    <Button type="button" variant="outline" size="icon" aria-label="Stop" onClick={onStop}>
      <SquareIcon />
    </Button>
  ) : (
    <Button
      type="submit"
      size="icon"
      aria-label="Send"
      disabled={text.trim().length === 0 || showPrompts}
      className={form === "dock" ? "size-8 rounded-lg shadow-[0_0_24px_-8px_var(--acc)]" : undefined}
    >
      <ArrowUpIcon />
    </Button>
  );

  const input = (
    <Textarea
      ref={ref}
      id={inputId}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={onKeyDown}
      disabled={streaming}
      maxLength={MAX_MESSAGE_CHARS}
      rows={1}
      placeholder={form === "full" ? COPY.fullPlaceholder : COPY.placeholder}
      aria-label="Message"
      className={cn(
        "resize-none",
        form === "dock"
          ? "min-h-8 flex-1 border-0 bg-transparent px-0 py-1 shadow-none focus-visible:ring-0"
          : form === "full"
            ? "max-h-48 min-h-12 border-0 bg-transparent px-0 text-[15px] shadow-none focus-visible:ring-0"
            : "max-h-32 min-h-9",
      )}
    />
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  if (form === "dock") {
    return (
      <form
        onSubmit={onSubmit}
        className="relative flex items-center gap-3 rounded-2xl border border-line-strong bg-surface-2 px-3.5 py-2 shadow-[0_0_0_4px_#4f7cff1f,0_12px_32px_-12px_#000a]"
      >
        {showPrompts ? <PromptList query={text.slice(1)} onPick={pickPrompt} /> : null}
        <MonoLabel className="text-acc">{COPY.dockLabel}</MonoLabel>
        {input}
        {fullScreenHref ? (
          <Link href={fullScreenHref as Route} className="shrink-0 text-[12px] text-soft hover:text-foreground">
            {COPY.fullScreen}
          </Link>
        ) : null}
        {send}
      </form>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <div className="relative flex flex-col gap-2 rounded-2xl border border-line-strong bg-surface-2 px-4 py-3">
        {showPrompts ? <PromptList query={text.slice(1)} onPick={pickPrompt} /> : null}
        {input}
        {form === "full" ? (
          <div className="flex items-center gap-2">
            <Attach
              staged={staged}
              onStaged={(added) => setStaged((s) => [...s, ...added])}
              onRemove={(id) => setStaged((s) => s.filter((x) => x.id !== id))}
              limits={uploadLimits}
              disabled={streaming}
            />
            {toolLabels.length > 0 ? (
              <Pill tone="muted" mono title="Tool groups you may use">
                {toolLabels.join(" · ")}
              </Pill>
            ) : null}
            <span className="ml-auto">{send}</span>
          </div>
        ) : (
          <div className="flex justify-end">{send}</div>
        )}
      </div>
      <HintRow form={form} />
    </form>
  );
}
