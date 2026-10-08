import type { ConfigValues, FieldSpec } from "../api/types";
import { fieldVisible } from "../lib/fields";
import { Help } from "./ui";

interface Props {
  fields: FieldSpec[];
  values: ConfigValues;
  onChange: (values: ConfigValues) => void;
  /** Column names offered by `column` / `columns` pickers (scope=table forms). */
  columns?: string[];
  idPrefix?: string;
  disabled?: boolean;
}

/** Renders any target's config/connection form generically from `FieldSpec`s. */
export function ConfigForm({ fields, values, onChange, columns = [], idPrefix = "f", disabled }: Props) {
  const set = (key: string, v: unknown) => onChange({ ...values, [key]: v });
  const visible = fields.filter((f) => fieldVisible(f, values));
  if (!visible.length) return <div className="muted small">No options for this scope.</div>;
  return (
    <div className="form-grid">
      {visible.map((f) => {
        const id = `${idPrefix}-${f.key}`;
        return (
          <div key={f.key} className={`field ${f.type === "columns" || f.type === "multiselect" ? "field-wide" : ""}`}>
            <label htmlFor={id}>
              {f.label}
              {f.required && <span className="req">*</span>}
              <Help text={f.help ?? (f.env ? `Pre-filled from $${f.env}` : null)} />
            </label>
            <FieldInput id={id} field={f} value={values[f.key]} onChange={(v) => set(f.key, v)} columns={columns} disabled={disabled} />
          </div>
        );
      })}
    </div>
  );
}

function FieldInput({ id, field: f, value, onChange, columns, disabled }: { id: string; field: FieldSpec; value: unknown; onChange: (v: unknown) => void; columns: string[]; disabled?: boolean }) {
  switch (f.type) {
    case "bool":
      return (
        <label className="toggle">
          <input id={id} type="checkbox" checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
          <span className="toggle-track" />
          <span className="small muted">{value ? "Yes" : "No"}</span>
        </label>
      );
    case "number":
      return (
        <input id={id} type="number" disabled={disabled} min={f.min ?? undefined} max={f.max ?? undefined} value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />
      );
    case "select":
      return (
        <select id={id} disabled={disabled} value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)}>
          {(!f.required || value == null) && <option value="">—</option>}
          {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    case "column":
      return (
        <select id={id} disabled={disabled} value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— none —</option>
          {columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      );
    case "multiselect":
    case "columns": {
      const options = f.type === "columns" ? columns : (f.options ?? []);
      const sel = Array.isArray(value) ? (value as string[]) : [];
      const full = f.max_items != null && sel.length >= f.max_items;
      return (
        <div className="chips-input" id={id}>
          {sel.map((c) => (
            <span key={c} className="chip chip-on">
              {c}
              {!disabled && <button type="button" aria-label={`Remove ${c}`} onClick={() => onChange(sel.filter((x) => x !== c))}>×</button>}
            </span>
          ))}
          <select aria-label={`Add to ${f.label}`} disabled={disabled || full} value="" onChange={(e) => e.target.value && onChange([...sel, e.target.value])}>
            <option value="">{full ? `max ${f.max_items}` : "+ add"}</option>
            {options.filter((o) => !sel.includes(o)).map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      );
    }
    default:
      return (
        <input id={id} type={f.type === "password" ? "password" : "text"} disabled={disabled} value={value == null ? "" : String(value)}
          placeholder={f.type === "file" ? "/path/to/file" : f.env ? `$${f.env}` : ""} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
      );
  }
}
