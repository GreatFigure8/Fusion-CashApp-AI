"use client";

import { useState } from "react";

import { Textarea } from "@/components/ui/textarea";

import type { EditorProps } from "./editor-props";

/** Fallback for structured values the UI has no dedicated editor for. The API validates the content. */
export function JsonEditor({ id, label, value, onChange, disabled, errors, describedBy }: EditorProps) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  return (
    <div className="space-y-1">
      <Textarea
        id={id}
        aria-label={label}
        aria-invalid={errors.length > 0 || parseError !== null}
        aria-describedby={describedBy}
        disabled={disabled}
        value={text}
        rows={Math.min(12, Math.max(3, text.split("\n").length))}
        className="font-mono text-xs"
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed: unknown = JSON.parse(e.target.value);
            setParseError(null);
            onChange(parsed);
          } catch {
            setParseError("Not valid JSON.");
            onChange(undefined);
          }
        }}
      />
      {parseError ? (
        <p role="alert" className="text-sm text-destructive">
          {parseError}
        </p>
      ) : null}
    </div>
  );
}
