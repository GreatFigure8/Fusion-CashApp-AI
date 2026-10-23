"use client";

import { useState, useTransition } from "react";

import { setSecret } from "@/app/(shell)/config/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { SECRET_NAME_PATTERN } from "../config-registry";
import type { EditorProps } from "./editor-props";

const SET_REASON = "Secret value set from the Settings page";

/**
 * The name of a stored secret, plus a write-only way to set its value. The value is encrypted by
 * the API and is never fetched or shown again.
 */
export function SecretRefEditor({ id, label, value, onChange, disabled, errors, describedBy }: EditorProps) {
  const name = typeof value === "string" ? value : "";
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<{ text: string; failed: boolean } | null>(null);
  const [pending, startTransition] = useTransition();
  const nameOk = new RegExp(SECRET_NAME_PATTERN).test(name);

  function save() {
    startTransition(async () => {
      const res = await setSecret({ name, value: draft, reason: SET_REASON });
      if (!res.ok) {
        setMessage({ text: res.error.message, failed: true });
        return;
      }
      setDraft("");
      setOpen(false);
      setMessage({ text: `Saved (version ${res.value.version}).`, failed: false });
    });
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={id}
          aria-label={label}
          aria-invalid={errors.length > 0}
          aria-describedby={describedBy}
          disabled={disabled}
          placeholder="secret-name"
          autoComplete="off"
          spellCheck={false}
          value={name}
          className="h-10 w-full min-w-0 px-3 font-mono text-sm sm:w-[480px]"
          onChange={(e) => onChange(e.target.value)}
        />
        <Button
          type="button"
          variant="outline"
          disabled={disabled || !nameOk || open}
          onClick={() => {
            setMessage(null);
            setOpen(true);
          }}
        >
          Set value
        </Button>
      </div>
      {open ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="password"
            aria-label={`${label} value`}
            autoComplete="new-password"
            spellCheck={false}
            value={draft}
            placeholder="Paste the secret"
            className="h-10 w-full min-w-0 px-3 font-mono text-sm sm:w-[480px]"
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button type="button" disabled={pending || draft.length === 0} onClick={save}>
            Save value
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={pending}
            onClick={() => {
              setDraft("");
              setOpen(false);
            }}
          >
            Cancel
          </Button>
        </div>
      ) : null}
      {message ? (
        <p role={message.failed ? "alert" : "status"} className={message.failed ? "text-sm text-err-ink" : "text-sm text-muted-foreground"}>
          {message.text}
        </p>
      ) : null}
    </div>
  );
}
