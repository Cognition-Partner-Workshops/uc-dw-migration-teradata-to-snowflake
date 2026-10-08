import type { ColumnPlan, ConfigValues, FieldSpec } from "../api/types";

export function fieldVisible(field: FieldSpec, values: ConfigValues): boolean {
  if (!field.show_if) return true;
  return Object.entries(field.show_if).every(([k, v]) => (Array.isArray(v) ? v.includes(values[k]) : values[k] === v));
}

export const fieldsInScope = (fields: FieldSpec[], scope: "target" | "table") =>
  fields.filter((f) => (f.scope ?? "target") === scope);

export function defaultsFor(fields: FieldSpec[]): ConfigValues {
  const out: ConfigValues = {};
  for (const f of fields) {
    if (f.default !== undefined && f.default !== null) out[f.key] = f.default;
    else if (f.type === "bool") out[f.key] = false;
    else if (f.type === "columns" || f.type === "multiselect") out[f.key] = [];
  }
  return out;
}

/** Values to submit: drops fields hidden by `show_if` and empty optional values. */
export function visibleValues(fields: FieldSpec[], values: ConfigValues): ConfigValues {
  const out: ConfigValues = {};
  for (const f of fields) {
    const v = values[f.key];
    if (!fieldVisible(f, values) || v === undefined || v === "" || v === null) continue;
    out[f.key] = v;
  }
  return out;
}

export function missingRequired(fields: FieldSpec[], values: ConfigValues): FieldSpec[] {
  return fields.filter((f) => f.required && fieldVisible(f, values) && (values[f.key] === undefined || values[f.key] === ""));
}

export const effectiveType = (c: ColumnPlan) => c.override_type || c.mapping.target_type;
