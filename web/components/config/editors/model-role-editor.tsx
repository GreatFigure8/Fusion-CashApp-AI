"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { EFFORTS, KNOWN_MODEL_IDS } from "../config-registry";
import { messageAt } from "../staging";
import type { EditorProps } from "./editor-props";
import { OptionSelect } from "./option-select";

const OTHER = "__other__";
const NO_EFFORT = "none";

type Role = { model_id: string; effort: string | null; timeout_s: number };

function toRole(value: unknown): Role {
  const o = (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
  return {
    model_id: typeof o["model_id"] === "string" ? o["model_id"] : "",
    effort: typeof o["effort"] === "string" ? o["effort"] : null,
    timeout_s: typeof o["timeout_s"] === "number" ? o["timeout_s"] : 0,
  };
}

/** One model role: model ID, effort and timeout. */
export function ModelRoleEditor({ id, label, value, onChange, disabled, errors }: EditorProps) {
  const initial = toRole(value);
  const [role, setRole] = useState<Role>(initial);
  const [timeoutText, setTimeoutText] = useState(String(initial.timeout_s));
  const [custom, setCustom] = useState(!KNOWN_MODEL_IDS.includes(initial.model_id));

  function commit(next: Role, timeoutRaw: string) {
    setRole(next);
    onChange({
      ...next,
      timeout_s: timeoutRaw.trim() === "" ? Number.NaN : Number(timeoutRaw),
    });
  }

  const modelError = messageAt(errors, "model_id");
  const effortError = messageAt(errors, "effort");
  const timeoutError = messageAt(errors, "timeout_s");
  const modelOptions = [
    ...KNOWN_MODEL_IDS.map((m) => ({ value: m, label: m })),
    { value: OTHER, label: "Other…" },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr]" role="group" aria-label={label}>
      <div className="space-y-1">
        <Label htmlFor={id}>Model ID</Label>
        <OptionSelect
          label={`${label} model`}
          value={custom ? OTHER : role.model_id}
          options={modelOptions}
          disabled={disabled}
          invalid={modelError !== undefined}
          className="w-full"
          onChange={(next) => {
            if (next === OTHER) {
              setCustom(true);
              return;
            }
            setCustom(false);
            commit({ ...role, model_id: next }, timeoutText);
          }}
        />
        {custom ? (
          <Input
            id={id}
            aria-label={`${label} custom model ID`}
            aria-invalid={modelError !== undefined}
            disabled={disabled}
            value={role.model_id}
            className="font-mono"
            onChange={(e) => commit({ ...role, model_id: e.target.value }, timeoutText)}
          />
        ) : null}
        {modelError ? (
          <p role="alert" className="text-sm text-destructive">
            {modelError}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        <Label>Effort</Label>
        <OptionSelect
          label={`${label} effort`}
          value={role.effort ?? NO_EFFORT}
          options={[...EFFORTS, NO_EFFORT].map((e) => ({ value: e, label: e }))}
          disabled={disabled}
          invalid={effortError !== undefined}
          className="w-full"
          onChange={(next) =>
            commit({ ...role, effort: next === NO_EFFORT ? null : next }, timeoutText)
          }
        />
        {effortError ? (
          <p role="alert" className="text-sm text-destructive">
            {effortError}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${id}-timeout`}>Timeout (s)</Label>
        <Input
          id={`${id}-timeout`}
          type="number"
          step="1"
          aria-invalid={timeoutError !== undefined}
          disabled={disabled}
          value={timeoutText}
          onChange={(e) => {
            setTimeoutText(e.target.value);
            commit(role, e.target.value);
          }}
        />
        {timeoutError ? (
          <p role="alert" className="text-sm text-destructive">
            {timeoutError}
          </p>
        ) : null}
      </div>
    </div>
  );
}
