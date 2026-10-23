import type { FieldError } from "../staging";

/** The contract every editor implements. `value` is the row's draft; `onChange` takes a raw, unvalidated next draft. */
export type EditorProps = Readonly<{
  id: string;
  label: string;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled: boolean;
  errors: readonly FieldError[];
  describedBy: string | undefined;
  unit: string | undefined;
}>;
