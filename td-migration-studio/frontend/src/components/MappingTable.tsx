import { useState } from "react";
import type { ColumnOverride, ColumnPlan, MaskingStrategy } from "../api/types";
import { effectiveType } from "../lib/fields";
import { errMsg } from "../lib/format";
import { Badge, Empty, type Tone } from "./ui";

export interface MappingRow {
  table: string;
  col: ColumnPlan;
}

export interface MappingFilters {
  lossyOnly: boolean;
  piiOnly: boolean;
  search: string;
}

export const NO_FILTERS: MappingFilters = { lossyOnly: false, piiOnly: false, search: "" };

export function filterMappingRows(rows: MappingRow[], f: MappingFilters): MappingRow[] {
  const q = f.search.trim().toLowerCase();
  return rows.filter(({ table, col }) => {
    if (f.lossyOnly && !col.mapping.lossy) return false;
    if (f.piiOnly && !col.pii) return false;
    if (!q) return true;
    return [table, col.source.name, col.source.td_type, effectiveType(col)].some((s) => s.toLowerCase().includes(q));
  });
}

const SEV_TONE: Record<string, Tone> = { info: "info", warning: "warn", error: "bad" };
const MASKS: MaskingStrategy[] = ["hash", "partial", "nullify", "none"];

interface Props {
  rows: MappingRow[];
  showTable?: boolean;
  editable?: boolean;
  onOverride?: (o: ColumnOverride) => Promise<void>;
  initialFilters?: Partial<MappingFilters>;
}

export function MappingTable({ rows, showTable, editable, onOverride, initialFilters }: Props) {
  const [filters, setFilters] = useState<MappingFilters>({ ...NO_FILTERS, ...initialFilters });
  const [editing, setEditing] = useState<string | null>(null);
  const visible = filterMappingRows(rows, filters);
  const lossy = rows.filter((r) => r.col.mapping.lossy).length;
  const pii = rows.filter((r) => r.col.pii).length;
  return (
    <div className="mapping">
      <div className="toolbar">
        <label className="chip-toggle">
          <input type="checkbox" checked={filters.lossyOnly} onChange={(e) => setFilters({ ...filters, lossyOnly: e.target.checked })} />
          Lossy only <Badge tone="warn">{lossy}</Badge>
        </label>
        <label className="chip-toggle">
          <input type="checkbox" checked={filters.piiOnly} onChange={(e) => setFilters({ ...filters, piiOnly: e.target.checked })} />
          PII only <Badge tone="accent">{pii}</Badge>
        </label>
        <input className="search" placeholder="Filter columns / types…" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        <span className="muted small grow-right">
          {visible.length} of {rows.length} columns
        </span>
      </div>
      {visible.length === 0 ? (
        <Empty>No columns match the current filters.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                {showTable && <th>Table</th>}
                <th>Source column</th>
                <th>Teradata type</th>
                <th>Target type</th>
                <th>Conversion</th>
                <th>PII</th>
                <th>Masking</th>
                {editable && <th />}
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const key = `${r.table}.${r.col.source.name}`;
                return editing === key ? (
                  <EditRow key={key} row={r} showTable={showTable} onCancel={() => setEditing(null)}
                    onSave={async (o) => { await onOverride?.(o); setEditing(null); }} />
                ) : (
                  <Row key={key} row={r} showTable={showTable} editable={editable} onEdit={() => setEditing(key)} />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ row: { table, col }, showTable, editable, onEdit }: { row: MappingRow; showTable?: boolean; editable?: boolean; onEdit: () => void }) {
  const m = col.mapping;
  return (
    <tr className={m.lossy ? `row-lossy row-${m.severity}` : ""}>
      {showTable && <td className="mono small">{table}</td>}
      <td className="mono">
        {col.source.name}
        {!col.source.nullable && <span className="muted small"> NN</span>}
      </td>
      <td className="mono small muted">{col.source.td_type.replace(/ NOT CASESPECIFIC/, "")}</td>
      <td className="mono">
        {col.overridden ? (
          <>
            <span className="strike muted">{m.target_type}</span> {effectiveType(col)} <Badge tone="accent">override</Badge>
          </>
        ) : (
          m.target_type
        )}
      </td>
      <td>
        {m.lossy ? (
          <span className="row gap-s wrap">
            <Badge tone={SEV_TONE[m.severity]}>LOSSY</Badge>
            <span className="small">{m.reason}</span>
            {m.transform && <Badge tone="muted">{m.transform}</Badge>}
          </span>
        ) : m.reason ? (
          <span className="small muted">{m.reason}</span>
        ) : (
          <span className="small muted">exact</span>
        )}
      </td>
      <td>
        {col.pii ? (
          <Badge tone="accent" title={`${col.pii.reason} (confidence ${Math.round(col.pii.confidence * 100)}%)`}>
            PII · {col.pii.category}
          </Badge>
        ) : (
          <span className="muted small">—</span>
        )}
      </td>
      <td className="small">{col.pii ? <span className={col.pii.masking === "none" ? "muted" : ""}>{col.pii.masking}</span> : <span className="muted">—</span>}</td>
      {editable && (
        <td className="right">
          <button className="btn btn-xs" onClick={onEdit}>Edit</button>
        </td>
      )}
    </tr>
  );
}

function EditRow({ row: { table, col }, showTable, onSave, onCancel }: { row: MappingRow; showTable?: boolean; onSave: (o: ColumnOverride) => Promise<void>; onCancel: () => void }) {
  const [type, setType] = useState(effectiveType(col));
  const [masking, setMasking] = useState<MaskingStrategy | "">(col.pii?.masking ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onSave({ table, column: col.source.name, target_type: type.trim() || null, masking: masking || null });
    } catch (e) {
      setErr(errMsg(e));
      setBusy(false);
    }
  };
  return (
    <tr className="row-edit">
      {showTable && <td className="mono small">{table}</td>}
      <td className="mono">{col.source.name}</td>
      <td className="mono small muted">{col.source.td_type.replace(/ NOT CASESPECIFIC/, "")}</td>
      <td>
        <input className="mono input-sm" aria-label="Target type" value={type} onChange={(e) => setType(e.target.value)} />
        <div className="small muted">mapped: {col.mapping.target_type}</div>
      </td>
      <td colSpan={2}>{err && <span className="text-bad small">{err}</span>}</td>
      <td>
        <select className="input-sm" aria-label="Masking" value={masking} onChange={(e) => setMasking(e.target.value as MaskingStrategy | "")}>
          {!col.pii && <option value="">(not PII)</option>}
          {MASKS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </td>
      <td className="right nowrap">
        <button className="btn btn-xs btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>{" "}
        <button className="btn btn-xs" disabled={busy} onClick={onCancel}>Cancel</button>
      </td>
    </tr>
  );
}
