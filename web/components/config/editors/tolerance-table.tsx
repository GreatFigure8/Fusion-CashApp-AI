"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { messageAt } from "../staging";
import type { EditorProps } from "./editor-props";

type Row = { currency: string; amount: string };

const FALLBACK = "*";

function toRows(value: unknown): Row[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return [];
  return Object.entries(value).map(([currency, amount]) => ({
    currency,
    amount: typeof amount === "string" ? amount : String(amount),
  }));
}

/** Per-currency tolerances as decimal strings, with the "*" fallback row fixed in place. */
export function ToleranceTable({ id, label, value, onChange, disabled, errors }: EditorProps) {
  const [rows, setRows] = useState<Row[]>(() => toRows(value));
  const [duplicate, setDuplicate] = useState<string | null>(null);

  function commit(next: Row[]) {
    setRows(next);
    const seen = new Set<string>();
    for (const r of next) {
      const key = r.currency.trim().toUpperCase();
      if (seen.has(key)) {
        setDuplicate(`${key} appears more than once.`);
        onChange(undefined);
        return;
      }
      seen.add(key);
    }
    setDuplicate(null);
    onChange(
      Object.fromEntries(
        next.map((r) => [r.currency === FALLBACK ? FALLBACK : r.currency.trim().toUpperCase(), r.amount]),
      ),
    );
  }

  return (
    <div className="space-y-2" role="group" aria-label={label}>
      {rows.map((row, i) => {
        const isFallback = row.currency === FALLBACK;
        const message = messageAt(errors, row.currency);
        return (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              {isFallback ? (
                <span className="w-44 text-sm">All other currencies</span>
              ) : (
                <Input
                  id={i === 0 ? id : undefined}
                  aria-label={`Currency code, row ${i + 1}`}
                  disabled={disabled}
                  value={row.currency}
                  maxLength={3}
                  className="w-44 font-mono uppercase"
                  onChange={(e) =>
                    commit(rows.map((r, j) => (j === i ? { ...r, currency: e.target.value } : r)))
                  }
                />
              )}
              <span aria-hidden="true">±</span>
              <Input
                aria-label={`Tolerance for ${isFallback ? "all other currencies" : row.currency || `row ${i + 1}`}`}
                aria-invalid={message !== undefined}
                disabled={disabled}
                inputMode="decimal"
                value={row.amount}
                className="w-28 font-mono"
                onChange={(e) =>
                  commit(rows.map((r, j) => (j === i ? { ...r, amount: e.target.value } : r)))
                }
              />
              {isFallback ? null : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={disabled}
                  aria-label={`Remove ${row.currency || `row ${i + 1}`}`}
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
        disabled={disabled}
        onClick={() => {
          const fallbackIndex = rows.findIndex((r) => r.currency === FALLBACK);
          const added: Row = { currency: "", amount: "0.10" };
          const next =
            fallbackIndex === -1
              ? [...rows, added]
              : [...rows.slice(0, fallbackIndex), added, ...rows.slice(fallbackIndex)];
          setRows(next);
          // An empty currency is not valid yet; the row validates once it has a code.
          commit(next);
        }}
      >
        <Plus aria-hidden="true" /> Add currency
      </Button>
    </div>
  );
}
