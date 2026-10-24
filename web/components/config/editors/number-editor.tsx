"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";

import type { EditorProps } from "./editor-props";

export function NumberEditor({ id, label, value, onChange, disabled, errors, describedBy, unit }: EditorProps) {
  const [text, setText] = useState(typeof value === "number" ? String(value) : "");
  return (
    <div className="flex items-center gap-2">
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        step="any"
        aria-label={label}
        aria-invalid={errors.length > 0}
        aria-describedby={describedBy}
        disabled={disabled}
        value={text}
        className="h-10 w-56 px-3 text-sm"
        onChange={(e) => {
          setText(e.target.value);
          onChange(e.target.value.trim() === "" ? Number.NaN : Number(e.target.value));
        }}
      />
      {unit ? <span className="text-sm text-muted-foreground">{unit}</span> : null}
    </div>
  );
}
