"use client";

import { useState, type KeyboardEvent } from "react";
import { SendIcon, SquareIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { MAX_MESSAGE_CHARS } from "./chat-schemas";

type ComposerProps = {
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
};

export function Composer({ streaming, onSend, onStop }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    const value = text.trim();
    if (streaming || value.length === 0) return;
    onSend(value);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    submit();
  };

  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={streaming}
        maxLength={MAX_MESSAGE_CHARS}
        rows={1}
        placeholder="Ask a question"
        aria-label="Message"
        className="max-h-32 min-h-9 resize-none"
      />
      {streaming ? (
        <Button type="button" variant="outline" size="icon" aria-label="Stop" onClick={onStop}>
          <SquareIcon />
        </Button>
      ) : (
        <Button type="submit" size="icon" aria-label="Send" disabled={text.trim().length === 0}>
          <SendIcon />
        </Button>
      )}
    </form>
  );
}
