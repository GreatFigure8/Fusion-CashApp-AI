"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { messageAt } from "../staging";
import type { EditorProps } from "./editor-props";

type Band = { currency: string; min_fee: string; max_fee: string };

function toBands(value: unknown): Band[] {
  if (!Array.isArray(value)) return [];
  return value.map((b: unknown) => {
    const o = (typeof b === "object" && b !== null ? b : {}) as Record<string, unknown>;
    return {
      currency: String(o["currency"] ?? ""),
      min_fee: String(o["min_fee"] ?? ""),
      max_fee: String(o["max_fee"] ?? ""),
    };
  });
}

/** Bank-fee bands: a fee between min and max explains a receipt shortfall in that currency. */
export function BankFeeBandsEditor({ id, label, value, onChange, disabled, errors }: EditorProps) {
  const [bands, setBands] = useState<Band[]>(() => toBands(value));

  function commit(next: Band[]) {
    setBands(next);
    onChange(next.map((b) => ({ ...b, currency: b.currency === "*" ? "*" : b.currency.trim().toUpperCase() })));
  }

  function patch(i: number, change: Partial<Band>) {
    commit(bands.map((b, j) => (j === i ? { ...b, ...change } : b)));
  }

  return (
    <div className="space-y-2" role="group" aria-label={label}>
      {bands.length === 0 ? (
        <p className="text-sm text-muted-foreground">No bank fee bands.</p>
      ) : null}
      {bands.map((band, i) => {
        const currencyError = messageAt(errors, `${i}.currency`);
        const minError = messageAt(errors, `${i}.min_fee`);
        const maxError = messageAt(errors, `${i}.max_fee`);
        return (
          <div key={i} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={i === 0 ? id : undefined}
                aria-label={`Currency, band ${i + 1}`}
                aria-invalid={currencyError !== undefined}
                disabled={disabled}
                value={band.currency}
                maxLength={3}
                className="w-20 font-mono uppercase"
                onChange={(e) => patch(i, { currency: e.target.value })}
              />
              <Input
                aria-label={`Minimum fee, band ${i + 1}`}
                aria-invalid={minError !== undefined}
                disabled={disabled}
                inputMode="decimal"
                value={band.min_fee}
                className="w-28 font-mono"
                onChange={(e) => patch(i, { min_fee: e.target.value })}
              />
              <span aria-hidden="true">to</span>
              <Input
                aria-label={`Maximum fee, band ${i + 1}`}
                aria-invalid={maxError !== undefined}
                disabled={disabled}
                inputMode="decimal"
                value={band.max_fee}
                className="w-28 font-mono"
                onChange={(e) => patch(i, { max_fee: e.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                disabled={disabled}
                aria-label={`Remove band ${i + 1}`}
                onClick={() => commit(bands.filter((_, j) => j !== i))}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
            {[currencyError, minError, maxError].map((m) =>
              m ? (
                <p key={m} role="alert" className="text-sm text-destructive">
                  {m}
                </p>
              ) : null,
            )}
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => commit([...bands, { currency: "", min_fee: "0.00", max_fee: "0.00" }])}
      >
        <Plus aria-hidden="true" /> Add band
      </Button>
    </div>
  );
}
