"use client";

import { Input } from "@/components/ui/input";

import type { EditorProps } from "./editor-props";

export function TextEditor({ id, label, value, onChange, disabled, errors, describedBy }: EditorProps) {
  return (
    <Input
      id={id}
      aria-label={label}
      aria-invalid={errors.length > 0}
      aria-describedby={describedBy}
      disabled={disabled}
      value={typeof value === "string" ? value : ""}
      className="h-10 w-full max-w-lg px-3 font-mono text-sm"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
