"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { messageAt } from "../staging";
import type { EditorProps } from "./editor-props";

/** An ordered list of delays in seconds, one for each successive retry. */
export function BackoffListEditor({ id, label, value, onChange, disabled, errors, describedBy }: EditorProps) {
  const [texts, setTexts] = useState<string[]>(() =>
    Array.isArray(value) ? value.map((v: unknown) => String(v)) : [],
  );

  function commit(next: string[]) {
    setTexts(next);
    onChange(next.map((t) => (t.trim() === "" ? Number.NaN : Number(t))));
  }

  return (
    <div className="space-y-2" role="group" aria-label={label} aria-describedby={describedBy}>
      {texts.map((text, i) => {
        const message = messageAt(errors, String(i));
        return (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-16 text-sm text-muted-foreground">Retry {i + 1}</span>
              <Input
                id={i === 0 ? id : undefined}
                type="number"
                step="1"
                aria-label={`Delay before retry ${i + 1}`}
                aria-invalid={message !== undefined}
                disabled={disabled}
                value={text}
                className="w-28"
                onChange={(e) => commit(texts.map((t, j) => (j === i ? e.target.value : t)))}
              />
              <span className="text-sm text-muted-foreground">s</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                disabled={disabled}
                aria-label={`Remove retry ${i + 1}`}
                onClick={() => commit(texts.filter((_, j) => j !== i))}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
            {message ? (
              <p role="alert" className="text-sm text-destructive">
                {message}
              </p>
            ) : null}
          </div>
        );
      })}
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => commit([...texts, "60"])}>
        <Plus aria-hidden="true" /> Add delay
      </Button>
    </div>
  );
}
