import type { ApiError } from "@/lib/api/errors";

import { saveOrder, uiFor, type EditorKind } from "./config-registry";
import type { JsonValue } from "./config-schemas";

export type FieldError = Readonly<{ path: string; message: string }>;

export type KeyResult =
  | { key: string; outcome: "saved"; version: number }
  | { key: string; outcome: "conflict"; currentVersion: number | null; message: string }
  | { key: string; outcome: "invalid"; fieldErrors: FieldError[]; message: string }
  | { key: string; outcome: "failed"; error: ApiError };

export type StagedBase = Readonly<{ value: JsonValue; version: number }>;

export type StagingState = Readonly<{
  /** The value and version each staged key had when it was first edited. */
  base: Readonly<Record<string, StagedBase>>;
  staged: Readonly<Record<string, JsonValue>>;
  errors: Readonly<Record<string, readonly FieldError[]>>;
  conflicts: ReadonlySet<string>;
  /** Bumped when rows must re-read their value (discard, save, reload). */
  epoch: number;
}>;

export type StagingAction =
  | { type: "stage"; key: string; value: JsonValue; base: StagedBase }
  | { type: "invalid"; key: string; errors: readonly FieldError[] }
  | { type: "unstage"; key: string }
  | { type: "discard" }
  | { type: "results"; results: readonly KeyResult[] };

export const initialStagingState: StagingState = {
  base: {},
  staged: {},
  errors: {},
  conflicts: new Set(),
  epoch: 0,
};

export function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ak = Object.keys(a);
  const bk = Object.keys(b);
  if (ak.length !== bk.length) return false;
  const bo = b as Record<string, unknown>;
  const ao = a as Record<string, unknown>;
  return ak.every((k) => k in bo && deepEqual(ao[k], bo[k]));
}

function without<T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> {
  const { [key]: _removed, ...rest } = record;
  void _removed;
  return rest;
}

export function stagingReducer(state: StagingState, action: StagingAction): StagingState {
  switch (action.type) {
    case "stage": {
      const baseEntry = state.base[action.key] ?? action.base;
      const errors = without(state.errors, action.key);
      const conflicts = new Set(state.conflicts);
      if (deepEqual(action.value, baseEntry.value)) {
        // Typing back to the original is not a change.
        conflicts.delete(action.key);
        return {
          ...state,
          base: without(state.base, action.key),
          staged: without(state.staged, action.key),
          errors,
          conflicts,
        };
      }
      return {
        ...state,
        base: { ...state.base, [action.key]: baseEntry },
        staged: { ...state.staged, [action.key]: action.value },
        errors,
      };
    }
    case "invalid":
      return { ...state, errors: { ...state.errors, [action.key]: action.errors } };
    case "unstage": {
      const conflicts = new Set(state.conflicts);
      conflicts.delete(action.key);
      return {
        ...state,
        base: without(state.base, action.key),
        staged: without(state.staged, action.key),
        errors: without(state.errors, action.key),
        conflicts,
        epoch: state.epoch + 1,
      };
    }
    case "discard":
      return { ...initialStagingState, epoch: state.epoch + 1 };
    case "results":
      return applySaveResults(state, action.results);
  }
}

export function stagedCount(state: StagingState): number {
  return Object.keys(state.staged).length;
}

export type StagedDiffRow = Readonly<{
  key: string;
  label: string;
  editor: EditorKind;
  unit: string | undefined;
  oldValue: JsonValue;
  newValue: JsonValue;
  expectedVersion: number;
}>;

/** Staged changes in save order (registry order, group-role map last). */
export function stagedDiff(state: StagingState): StagedDiffRow[] {
  return Object.keys(state.staged)
    .sort((a, b) => saveOrder(a) - saveOrder(b))
    .map((key) => {
      const ui = uiFor(key);
      const base = state.base[key];
      return {
        key,
        label: ui.label,
        editor: ui.editor,
        unit: ui.unit,
        oldValue: base?.value ?? null,
        newValue: state.staged[key] ?? null,
        expectedVersion: base?.version ?? 0,
      };
    });
}

/** Saved keys leave staging; invalid keys keep their value and gain field errors; conflicts are flagged. */
export function applySaveResults(
  state: StagingState,
  results: readonly KeyResult[],
): StagingState {
  let base = { ...state.base };
  let staged = { ...state.staged };
  const errors: Record<string, readonly FieldError[]> = { ...state.errors };
  const conflicts = new Set(state.conflicts);
  for (const result of results) {
    switch (result.outcome) {
      case "saved":
        base = without(base, result.key);
        staged = without(staged, result.key);
        delete errors[result.key];
        conflicts.delete(result.key);
        break;
      case "conflict":
        conflicts.add(result.key);
        break;
      case "invalid":
        errors[result.key] = result.fieldErrors;
        break;
      case "failed":
        break;
    }
  }
  return { base, staged, errors, conflicts, epoch: state.epoch + 1 };
}

/**
 * Turns the API's validation `details` ({loc, msg}) into field errors. The leading `body` and
 * `value` segments are dropped; the rest addresses the field inside the editor.
 */
export function fieldErrorsFromLoc(details: ApiError["details"]): FieldError[] {
  const out: FieldError[] = [];
  for (const d of details) {
    const loc = d["loc"];
    const msg = d["msg"];
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const parts = loc.map((p) => String(p));
    while (parts[0] === "body" || parts[0] === "value") parts.shift();
    out.push({ path: parts.join("."), message: msg });
  }
  return out;
}

/** The message for exactly this path. */
export function messageAt(errors: readonly FieldError[], path: string): string | undefined {
  return errors.find((e) => e.path === path)?.message;
}
