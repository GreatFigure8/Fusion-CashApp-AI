"use client";

import type { ComponentType } from "react";
import { useState } from "react";

import { Pill } from "@/components/common/pill";
import { cn } from "@/lib/utils";
import type { Schemas } from "@/lib/api/types";

import { ChangedByLink } from "./changed-by-link";
import { useStaging } from "./config-staging-provider";
import { uiForEntry, type EditorKind } from "./config-registry";
import { jsonValueSchema, schemaForEditor, type JsonValue } from "./config-schemas";
import { BackoffListEditor } from "./editors/backoff-list-editor";
import { BankFeeBandsEditor } from "./editors/bank-fee-bands-editor";
import { DecimalNullableEditor } from "./editors/decimal-nullable-editor";
import type { EditorProps } from "./editors/editor-props";
import { GroupRoleEditor } from "./editors/group-role-editor";
import { JsonEditor } from "./editors/json-editor";
import { MaxAttemptsEditor } from "./editors/max-attempts-editor";
import { ModelRoleEditor } from "./editors/model-role-editor";
import { NullableDaysEditor } from "./editors/nullable-days-editor";
import { NumberEditor } from "./editors/number-editor";
import { SecretRefEditor } from "./editors/secret-ref-editor";
import { SwitchEditor } from "./editors/switch-editor";
import { TextEditor } from "./editors/text-editor";
import { ToleranceTable } from "./editors/tolerance-table";
import type { FieldError } from "./staging";
import { lastChangedLabel } from "./value-format";

const EDITORS: Record<EditorKind, ComponentType<EditorProps>> = {
  number: NumberEditor,
  "nullable-days": NullableDaysEditor,
  "tolerance-table": ToleranceTable,
  "bank-fee-bands": BankFeeBandsEditor,
  "backoff-list": BackoffListEditor,
  "max-attempts": MaxAttemptsEditor,
  "model-role": ModelRoleEditor,
  "group-roles": GroupRoleEditor,
  switch: SwitchEditor,
  "secret-ref": SecretRefEditor,
  text: TextEditor,
  "decimal-nullable": DecimalNullableEditor,
  json: JsonEditor,
};

/** Editors that render errors for their own sub-fields; the row shows only whole-value errors for these. */
const NESTED: ReadonlySet<EditorKind> = new Set([
  "tolerance-table",
  "bank-fee-bands",
  "backoff-list",
  "max-attempts",
  "model-role",
  "group-roles",
]);

const EDITOR_INVALID = "Fix the highlighted fields.";

type RowEntry = Pick<
  Schemas["ConfigEntry"],
  "key" | "value" | "version" | "description"
> &
  Partial<
    Pick<
      Schemas["ConfigEntry"],
      "restart_required" | "secret_ref" | "last_changed_at" | "last_changed_by"
    >
  >;

/** One setting: label, description, editor, unit, "Modified" dot, errors and the changed-by link. */
export function SettingRow({ entry }: { entry: RowEntry }) {
  const { state } = useStaging();
  // Re-mounts when staging resets or the server value moves, so drafts never go stale.
  return (
    <SettingRowInner
      key={`${entry.key}:${state.epoch}:${entry.version}`}
      entry={entry}
    />
  );
}

function SettingRowInner({ entry }: { entry: RowEntry }) {
  const { state, dispatch, canEdit } = useStaging();
  const ui = uiForEntry(entry);
  const base = jsonValueSchema.safeParse(entry.value);
  const baseValue: JsonValue = base.success ? base.data : null;
  const [draft, setDraft] = useState<unknown>(state.staged[entry.key] ?? baseValue);

  const errors: readonly FieldError[] = state.errors[entry.key] ?? [];
  const rowErrors = NESTED.has(ui.editor) ? errors.filter((e) => e.path === "") : errors;
  const staged = entry.key in state.staged;
  const conflict = state.conflicts.has(entry.key);
  const Editor = EDITORS[ui.editor];
  const id = `setting-${entry.key.replace(/[^a-z0-9]+/gi, "-")}`;
  const errorId = `${id}-errors`;
  const schema = schemaForEditor(ui.editor, ui);

  function handleChange(next: unknown) {
    setDraft(next);
    if (next === undefined) {
      dispatch({ type: "invalid", key: entry.key, errors: [{ path: "", message: EDITOR_INVALID }] });
      return;
    }
    const parsed = schema.safeParse(next);
    if (!parsed.success) {
      dispatch({
        type: "invalid",
        key: entry.key,
        errors: parsed.error.issues.map((i) => ({
          path: i.path.map(String).join("."),
          message: i.message,
        })),
      });
      return;
    }
    const value = jsonValueSchema.safeParse(parsed.data);
    if (!value.success) return;
    dispatch({
      type: "stage",
      key: entry.key,
      value: value.data,
      base: { value: baseValue, version: entry.version },
    });
  }

  const secret = entry.secret_ref === true;
  const label = lastChangedLabel({
    staged,
    at: entry.last_changed_at,
    by: entry.last_changed_by,
  });

  return (
    <section
      aria-labelledby={`${id}-label`}
      data-dirty={staged ? "true" : undefined}
      className={cn(
        "space-y-2 border-t border-line px-4 py-3 first:border-t-0",
        !canEdit && "opacity-80",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <h3 id={`${id}-label`} className="flex flex-wrap items-center gap-2 font-mono text-[13px]">
            {entry.key}
            {entry.restart_required ? <Pill tone="muted">restart required</Pill> : null}
            {secret ? <Pill tone="locked">Stored secret</Pill> : null}
          </h3>
          <p className="text-sm text-muted-foreground">{entry.description}</p>
        </div>
        <ChangedByLink settingKey={entry.key} label={label} />
      </div>
      <div
        className={cn(
          "rounded-lg border border-transparent p-1",
          staged && "border-brand-hi shadow-[0_0_0_3px_var(--halo)]",
        )}
      >
        <Editor
          id={id}
          label={ui.label}
          value={draft}
          onChange={handleChange}
          disabled={!canEdit}
          errors={errors}
          describedBy={rowErrors.length > 0 ? errorId : undefined}
          unit={ui.unit}
        />
      </div>
      {rowErrors.length > 0 ? (
        <ul id={errorId} role="alert" className="space-y-0.5 text-sm text-err-ink">
          {rowErrors.map((e, i) => (
            <li key={i}>{e.path && !NESTED.has(ui.editor) ? `${e.path}: ${e.message}` : e.message}</li>
          ))}
        </ul>
      ) : null}
      {conflict ? (
        <p role="alert" className="text-sm text-err-ink">
          This setting was changed by someone else since you opened it.
        </p>
      ) : null}
    </section>
  );
}
