import type { EditorKind } from "./config-registry";
import type { JsonValue } from "./config-schemas";

type Obj = Record<string, JsonValue>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function withUnit(v: JsonValue, unit: string | undefined): string {
  return unit ? `${String(v)} ${unit}` : String(v);
}

/** One readable string for a value; used by rows, the review dialog and history. */
export function formatConfigValue(
  editor: EditorKind,
  value: JsonValue,
  unit?: string,
): string {
  switch (editor) {
    case "number":
      return value === null ? "—" : withUnit(value, unit);
    case "nullable-days":
      return value === null ? "Keep indefinitely" : `${String(value)} days`;
    case "decimal-nullable":
      return value === null ? "No limit" : withUnit(value, unit);
    case "tolerance-table":
      if (!isObj(value)) return JSON.stringify(value);
      return Object.entries(value)
        .map(([cur, amt]) => `±${String(amt)} ${cur === "*" ? "any other" : cur}`)
        .join(", ");
    case "bank-fee-bands":
      if (!Array.isArray(value)) return JSON.stringify(value);
      if (value.length === 0) return "None";
      return value
        .map((b) =>
          isObj(b) ? `${String(b["currency"])} ${String(b["min_fee"])}–${String(b["max_fee"])}` : "?",
        )
        .join(", ");
    case "backoff-list":
      return Array.isArray(value) ? value.map((s) => `${String(s)} s`).join(", ") : String(value);
    case "max-attempts":
      if (!isObj(value)) return JSON.stringify(value);
      return Object.entries(value)
        .map(([code, n]) => `${code === "*" ? "any other" : code}: ${String(n)}`)
        .join(", ");
    case "model-role":
      if (!isObj(value)) return JSON.stringify(value);
      return [
        String(value["model_id"]),
        value["effort"] === null ? "no effort" : String(value["effort"]),
        `${String(value["timeout_s"])} s`,
      ].join(" · ");
    case "group-roles":
      if (!Array.isArray(value)) return JSON.stringify(value);
      if (value.length === 0) return "No mappings";
      return value
        .map((m) => (isObj(m) ? `${String(m["group_name"])} → ${String(m["role"])}` : "?"))
        .join(", ");
    case "switch":
      return value === true ? "On" : "Off";
    case "text":
      return typeof value === "string" ? value : JSON.stringify(value);
    case "json":
      return JSON.stringify(value);
  }
}
