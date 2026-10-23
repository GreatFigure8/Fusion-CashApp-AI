"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import type { EditorProps } from "./editor-props";

/** A decimal string (never a Number) or "No limit" (null). */
export function DecimalNullableEditor({ id, label, value, onChange, disabled, errors, describedBy, unit }: EditorProps) {
  const unlimited = value === null;
  const [text, setText] = useState(typeof value === "string" ? value : "0.00");
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-2">
        <Switch
          id={`${id}-unlimited`}
          checked={unlimited}
          disabled={disabled}
          onCheckedChange={(checked) => onChange(checked ? null : text)}
        />
        <Label htmlFor={`${id}-unlimited`}>No limit</Label>
      </div>
      {unlimited ? null : (
        <div className="flex items-center gap-2">
          <Input
            id={id}
            inputMode="decimal"
            aria-label={label}
            aria-invalid={errors.length > 0}
            aria-describedby={describedBy}
            disabled={disabled}
            value={text}
            className="w-32 font-mono"
            onChange={(e) => {
              setText(e.target.value);
              onChange(e.target.value);
            }}
          />
          {unit ? <span className="text-sm text-muted-foreground">{unit}</span> : null}
        </div>
      )}
    </div>
  );
}
