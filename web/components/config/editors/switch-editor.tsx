"use client";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import type { EditorProps } from "./editor-props";

export function SwitchEditor({ id, label, value, onChange, disabled, describedBy }: EditorProps) {
  return (
    <div className="flex items-center gap-2">
      <Switch
        id={id}
        checked={value === true}
        disabled={disabled}
        aria-describedby={describedBy}
        onCheckedChange={(checked) => onChange(checked)}
      />
      <Label htmlFor={id}>{value === true ? "On" : "Off"}</Label>
      <span className="sr-only">{label}</span>
    </div>
  );
}
