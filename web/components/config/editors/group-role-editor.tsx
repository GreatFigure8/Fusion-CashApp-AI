"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { ROLES } from "../config-registry";
import { messageAt } from "../staging";
import type { EditorProps } from "./editor-props";
import { OptionSelect } from "./option-select";

type Mapping = { group_name: string; role: string };

function toMappings(value: unknown): Mapping[] {
  if (!Array.isArray(value)) return [];
  return value.map((m: unknown) => {
    const o = (typeof m === "object" && m !== null ? m : {}) as Record<string, unknown>;
    return { group_name: String(o["group_name"] ?? ""), role: String(o["role"] ?? "VIEWER") };
  });
}

const ROLE_OPTIONS = ROLES.map((r) => ({ value: r, label: r }));

/** Identity-domain group name to app role. Staged under `access.group_role_map` like any other setting. */
export function GroupRoleEditor({ id, label, value, onChange, disabled, errors }: EditorProps) {
  const [mappings, setMappings] = useState<Mapping[]>(() => toMappings(value));

  function commit(next: Mapping[]) {
    setMappings(next);
    onChange(next);
  }

  return (
    <div className="space-y-2" role="group" aria-label={label}>
      {mappings.length === 0 ? (
        <p className="text-sm text-muted-foreground">No group mappings.</p>
      ) : null}
      {mappings.map((m, i) => {
        const message = messageAt(errors, `${i}.group_name`);
        return (
          <div key={i} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={i === 0 ? id : undefined}
                aria-label={`Group name, row ${i + 1}`}
                aria-invalid={message !== undefined}
                disabled={disabled}
                value={m.group_name}
                className="w-72"
                onChange={(e) =>
                  commit(mappings.map((x, j) => (j === i ? { ...x, group_name: e.target.value } : x)))
                }
              />
              <span aria-hidden="true">→</span>
              <OptionSelect
                label={`Role for ${m.group_name || `row ${i + 1}`}`}
                value={m.role}
                options={ROLE_OPTIONS}
                disabled={disabled}
                className="w-40"
                onChange={(role) =>
                  commit(mappings.map((x, j) => (j === i ? { ...x, role } : x)))
                }
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                disabled={disabled}
                aria-label={`Remove ${m.group_name || `row ${i + 1}`}`}
                onClick={() => commit(mappings.filter((_, j) => j !== i))}
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
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => commit([...mappings, { group_name: "", role: "VIEWER" }])}
      >
        <Plus aria-hidden="true" /> Add group
      </Button>
    </div>
  );
}
