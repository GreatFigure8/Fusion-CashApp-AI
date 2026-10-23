"use client";

import { Input } from "@/components/ui/input";

import type { EditorProps } from "./editor-props";

/** A Vault secret OCID as plain text. The secret itself is never fetched or shown. */
export function SecretRefEditor({ id, label, value, onChange, disabled, errors, describedBy }: EditorProps) {
  return (
    <Input
      id={id}
      aria-label={label}
      aria-invalid={errors.length > 0}
      aria-describedby={describedBy}
      disabled={disabled}
      placeholder="ocid1.vaultsecret.…"
      autoComplete="off"
      spellCheck={false}
      value={typeof value === "string" ? value : ""}
      className="w-full min-w-0 font-mono text-[13px] sm:w-[420px]"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
