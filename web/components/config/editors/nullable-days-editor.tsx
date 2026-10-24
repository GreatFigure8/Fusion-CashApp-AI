"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import type { EditorProps } from "./editor-props";

const DEFAULT_DAYS = 365;

/** A day count, or "Keep indefinitely" (null). */
export function NullableDaysEditor({ id, label, value, onChange, disabled, errors, describedBy }: EditorProps) {
  const indefinite = value === null;
  const [text, setText] = useState(typeof value === "number" ? String(value) : String(DEFAULT_DAYS));
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-2">
        <Switch
          id={`${id}-indefinite`}
          checked={indefinite}
          disabled={disabled}
          onCheckedChange={(checked) =>
            onChange(checked ? null : text.trim() === "" ? Number.NaN : Number(text))
          }
        />
        <Label htmlFor={`${id}-indefinite`}>Keep indefinitely</Label>
      </div>
      {indefinite ? null : (
        <div className="flex items-center gap-2">
          <Input
            id={id}
            type="number"
            step="1"
            aria-label={label}
            aria-invalid={errors.length > 0}
            aria-describedby={describedBy}
            disabled={disabled}
            value={text}
            className="h-10 w-40 px-3 text-sm"
            onChange={(e) => {
              setText(e.target.value);
              onChange(e.target.value.trim() === "" ? Number.NaN : Number(e.target.value));
            }}
          />
          <span className="text-sm text-muted-foreground">days</span>
        </div>
      )}
    </div>
  );
}
