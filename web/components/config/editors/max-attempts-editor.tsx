"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { ERROR_CODES } from "../config-registry";
import { messageAt } from "../staging";
import type { EditorProps } from "./editor-props";
import { OptionSelect } from "./option-select";

type Row = { code: string; attempts: string };

const FALLBACK = "*";

function toRows(value: unknown): Row[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return [];
  return Object.entries(value).map(([code, n]) => ({ code, attempts: String(n) }));
}

/** Maximum auto-fix attempts per error code, with the "*" fallback row fixed in place. */
export function MaxAttemptsEditor({ id, label, value, onChange, disabled, errors }: EditorProps) {
  const [rows, setRows] = useState<Row[]>(() => toRows(value));
  const [duplicate, setDuplicate] = useState<string | null>(null);

  function commit(next: Row[]) {
    setRows(next);
    const seen = new Set<string>();
    for (const r of next) {
      if (seen.has(r.code)) {
        setDuplicate(`${r.code} appears more than once.`);
        onChange(undefined);
        return;
      }
      seen.add(r.code);
    }
    setDuplicate(null);
    onChange(
      Object.fromEntries(next.map((r) => [r.code, r.attempts.trim() === "" ? Number.NaN : Number(r.attempts)])),
    );
  }

  const unused = ERROR_CODES.filter((c) => !rows.some((r) => r.code === c));
  const options = (current: string) =>
    [current, ...unused].filter(Boolean).map((c) => ({ value: c, label: c }));

  return (
    <div className="space-y-2" role="group" aria-label={label}>
      {rows.map((row, i) => {
        const isFallback = row.code === FALLBACK;
        const message = messageAt(errors, row.code);
        return (
          <div key={row.code} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              {isFallback ? (
                <span className="w-72 text-sm">All other codes</span>
              ) : (
                <OptionSelect
                  label={`Error code, row ${i + 1}`}
                  value={row.code}
                  options={options(row.code)}
                  disabled={disabled}
                  className="w-72"
                  onChange={(code) => commit(rows.map((r, j) => (j === i ? { ...r, code } : r)))}
                />
              )}
              <Input
                id={i === 0 ? id : undefined}
                type="number"
                step="1"
                aria-label={`Maximum attempts for ${isFallback ? "all other codes" : row.code}`}
                aria-invalid={message !== undefined}
                disabled={disabled}
                value={row.attempts}
                className="w-24"
                onChange={(e) =>
                  commit(rows.map((r, j) => (j === i ? { ...r, attempts: e.target.value } : r)))
                }
              />
              {isFallback ? null : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={disabled}
                  aria-label={`Remove ${row.code}`}
                  onClick={() => commit(rows.filter((_, j) => j !== i))}
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              )}
            </div>
            {message ? (
              <p role="alert" className="text-sm text-destructive">
                {message}
              </p>
            ) : null}
          </div>
        );
      })}
      {duplicate ? (
        <p role="alert" className="text-sm text-destructive">
          {duplicate}
        </p>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || unused.length === 0}
        onClick={() => {
          const first = unused[0];
          if (first === undefined) return;
          const at = rows.findIndex((r) => r.code === FALLBACK);
          const added: Row = { code: first, attempts: "3" };
          commit(at === -1 ? [...rows, added] : [...rows.slice(0, at), added, ...rows.slice(at)]);
        }}
      >
        <Plus aria-hidden="true" /> Add error code
      </Button>
    </div>
  );
}
