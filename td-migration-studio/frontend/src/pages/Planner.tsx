import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ConnectionTestResult, DQThresholds, SourceConnection, FailureStage, MaskingStrategy, PlanRequest, TableMeta, TargetMeta } from "../api/types";
import { ConfigForm } from "../components/ConfigForm";
import { Badge, Card, Empty, ErrorBox, Help, Spinner, Toggle } from "../components/ui";
import { defaultsFor, fieldsInScope, missingRequired, visibleValues } from "../lib/fields";
import { errMsg, fmtBytes, fmtCompact, fmtInt } from "../lib/format";
import { navigate, useAsync } from "../lib/hooks";
import type { PlannerState } from "./plannerState";

interface Props {
  state: PlannerState;
  setState: (fn: (s: PlannerState) => PlannerState) => void;
}

export function Planner({ state, setState }: Props) {
  const patch = (p: Partial<PlannerState>) => setState((s) => ({ ...s, ...p }));
  const conn = useAsync(() => api.sourceConnection(), []);
  const dbs = useAsync(() => api.databases(), []);
  const tables = useAsync(() => api.tables(state.database), [state.database]);
  const targets = useAsync(() => api.targets(), []);
  const meta = useAsync(() => (state.targetId ? api.target(state.targetId) : Promise.resolve(null)), [state.targetId]);
  const [cols, setCols] = useState<Record<string, TableMeta>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Defaults: select all tables, pick the first target.
  useEffect(() => {
    if (tables.data && state.selected === null) patch({ selected: tables.data.map((t) => t.name) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tables.data]);
  useEffect(() => {
    if (targets.data?.length && !state.targetId) patch({ targetId: targets.data.find((t) => t.id === "bigquery")?.id ?? targets.data[0].id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targets.data]);
  // Re-seed config defaults when the target metadata changes.
  useEffect(() => {
    const m = meta.data;
    if (!m) return;
    setState((s) => {
      if (s.targetConfig.__target === m.id) return s;
      const tableDefaults = defaultsFor(fieldsInScope(m.config_fields, "table"));
      const tableConfig = Object.fromEntries((tables.data ?? []).map((t) => [t.name, { ...tableDefaults }]));
      return { ...s, targetConfig: { ...defaultsFor(fieldsInScope(m.config_fields, "target")), __target: m.id }, tableConfig, connection: defaultsFor(m.connection_fields) };
    });
  }, [meta.data, tables.data, setState]);

  const selected = useMemo(() => state.selected ?? [], [state.selected]);
  const selectedRows = (tables.data ?? []).filter((t) => selected.includes(t.name)).reduce((a, t) => a + (t.row_count ?? 0), 0);
  const m = meta.data;
  const summary = targets.data?.find((t) => t.id === state.targetId);

  const loadCols = async (name: string) => {
    if (cols[name]) return;
    try {
      const t = await api.table(state.database, name);
      setCols((c) => ({ ...c, [name]: t }));
    } catch (e) {
      setSubmitError(errMsg(e));
    }
  };

  const problems: string[] = [];
  if (!selected.length) problems.push("Select at least one table");
  if (m) {
    missingRequired(fieldsInScope(m.config_fields, "target"), state.targetConfig).forEach((f) => problems.push(`${f.label} is required`));
    if (state.targetMode === "real")
      missingRequired(m.connection_fields, state.connection).forEach((f) => problems.push(`Connection: ${f.label} is required`));
  }

  const generate = async () => {
    if (!m) return;
    setSubmitting(true);
    setSubmitError(null);
    const tableFields = fieldsInScope(m.config_fields, "table");
    const req: PlanRequest = {
      source_database: state.database,
      tables: selected,
      target_id: m.id,
      target_mode: state.targetMode,
      target_connection: state.targetMode === "real" ? visibleValues(m.connection_fields, state.connection) : {},
      target_config: visibleValues(fieldsInScope(m.config_fields, "target"), state.targetConfig),
      table_config: Object.fromEntries(selected.map((t) => [t, visibleValues(tableFields, state.tableConfig[t] ?? {})])),
      dq: state.dq,
      governance: state.governance,
      options: { ...state.options, inject_failures: state.inject.enabled && selected.includes(state.inject.table) ? [{ table: state.inject.table, stage: state.inject.stage, times: state.inject.times }] : [] },
    };
    try {
      const plan = await api.createPlan(req);
      navigate(`/plans/${plan.id}`);
    } catch (e) {
      setSubmitError(errMsg(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="page">
      <div className="grid-2">
        <SourcePanel conn={conn} databases={dbs.data ?? []} database={state.database} onDatabase={(database) => patch({ database, selected: null })} tablesFound={tables.data?.length} />
        <Card title="Target warehouse">
          {targets.error ? <ErrorBox error={targets.error} onRetry={targets.reload} /> : !targets.data ? <Spinner /> : (
            <>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="target">Target</label>
                  <select id="target" value={state.targetId} onChange={(e) => patch({ targetId: e.target.value, targetMode: "simulated" })}>
                    {targets.data.map((t) => <option key={t.id} value={t.id}>{t.display_name} — {t.vendor}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Mode</label>
                  <div className="segmented">
                    {(["simulated", "real"] as const).map((md) => (
                      <button key={md} className={state.targetMode === md ? "active" : ""} disabled={!summary?.modes.includes(md)} onClick={() => patch({ targetMode: md })}>
                        {md === "simulated" ? "Simulated (DuckDB)" : "Real"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {summary && (
                <div className="row gap-s wrap mt-s">
                  <Badge tone="ok">simulated available</Badge>
                  <Badge tone={summary.real_ready ? "ok" : "muted"} title={m ? `Requires ${m.real_mode_required_env.join(", ")}` : undefined}>
                    real: {summary.real_ready ? "credentials detected" : "no credentials"}
                  </Badge>
                  {m && <span className="small muted">{m.description}</span>}
                </div>
              )}
              {summary?.free_tier_note && <div className="alert alert-info mt-s small"><strong>Free sandbox:</strong> {summary.free_tier_note}</div>}
              {state.targetMode === "real" && m && <TargetConnection meta={m} values={state.connection} onChange={(connection) => patch({ connection })} />}
            </>
          )}
        </Card>
      </div>

      <div className="grid-2 grid-scope">
        <Card title={`Scope — ${state.database}`} actions={tables.data && (
          <>
            <button className="btn btn-xs" onClick={() => patch({ selected: tables.data!.map((t) => t.name) })}>Select all</button>
            <button className="btn btn-xs" onClick={() => patch({ selected: [] })}>None</button>
          </>
        )} pad={false}>
          {tables.error ? <div className="card-body"><ErrorBox error={tables.error} onRetry={tables.reload} /></div> : !tables.data ? <div className="card-body"><Spinner /></div> : tables.data.length === 0 ? <Empty>No tables in {state.database}</Empty> : (
            <table className="grid">
              <thead><tr><th style={{ width: 28 }} /><th>Table</th><th>Kind</th><th className="right">Columns</th><th className="right">Rows</th><th className="right">Size</th></tr></thead>
              <tbody>
                {tables.data.map((t) => (
                  <tr key={t.name} className="clickable" onClick={() => patch({ selected: selected.includes(t.name) ? selected.filter((x) => x !== t.name) : [...selected, t.name] })}>
                    <td><input type="checkbox" aria-label={t.name} checked={selected.includes(t.name)} readOnly /></td>
                    <td className="mono">{t.name}</td>
                    <td><Badge tone={t.kind === "SET" ? "info" : "muted"}>{t.kind}</Badge></td>
                    <td className="right">{t.column_count}</td>
                    <td className="right mono">{fmtInt(t.row_count)}</td>
                    <td className="right muted small">{fmtBytes(t.size_bytes)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><td /><td colSpan={3}>{selected.length} of {tables.data.length} selected</td><td className="right mono">{fmtInt(selectedRows)}</td><td /></tr></tfoot>
            </table>
          )}
        </Card>

        <Card title={m ? `${m.display_name} configuration` : "Target configuration"}>
          {meta.error ? <ErrorBox error={meta.error} onRetry={meta.reload} /> : !m ? <Spinner /> : (
            <>
              <h4 className="section-title">Target-level</h4>
              <ConfigForm idPrefix="tgt" fields={fieldsInScope(m.config_fields, "target")} values={state.targetConfig} onChange={(targetConfig) => patch({ targetConfig })} />
              <h4 className="section-title mt">Per-table options <span className="muted small">({fieldsInScope(m.config_fields, "table").map((f) => f.label).join(", ")})</span></h4>
              <div className="accordion">
                {selected.map((name) => (
                  <details key={name} onToggle={(e) => (e.target as HTMLDetailsElement).open && loadCols(name)}>
                    <summary>
                      <span className="mono">{name}</span>
                      <span className="muted small">{tableOptsSummary(m, state.tableConfig[name])}</span>
                    </summary>
                    <div className="details-body">
                      {cols[name] ? (
                        <ConfigForm idPrefix={`tbl-${name}`} fields={fieldsInScope(m.config_fields, "table")} values={state.tableConfig[name] ?? {}} columns={cols[name].columns.map((c) => c.name)}
                          onChange={(v) => setState((s) => ({ ...s, tableConfig: { ...s.tableConfig, [name]: v } }))} />
                      ) : <Spinner label="Loading columns…" />}
                    </div>
                  </details>
                ))}
                {!selected.length && <Empty>Select tables to configure per-table options.</Empty>}
              </div>
            </>
          )}
        </Card>
      </div>

      <div className="grid-3">
        <Card title="Data-quality checks">
          <div className="toggle-list">
            {([
              ["row_count", "Row count", "source − rejected vs target"],
              ["aggregates", "Aggregates", "sum / min / max per numeric column"],
              ["null_ratio", "Null ratio", "per column, staged vs target"],
              ["checksum", "Checksum", "canonical row checksum (contracts/checksum.py)"],
              ["uniqueness", "Uniqueness", "on UPI / USI logical keys"],
              ["referential_integrity", "Referential integrity", "orphans on soft RI foreign keys"],
            ] as const).map(([k, label, help]) => (
              <Toggle key={k} label={label} help={help} checked={state.dq[k]} onChange={(v) => patch({ dq: { ...state.dq, [k]: v } })} />
            ))}
          </div>
          <h4 className="section-title mt">Thresholds (%)</h4>
          <div className="form-grid form-grid-tight">
            {([
              ["row_count_tolerance_pct", "Row count tolerance"],
              ["aggregate_tolerance_pct", "Aggregate tolerance"],
              ["null_ratio_tolerance_pct", "Null-ratio tolerance"],
              ["max_rejected_rows_pct", "Max rejected rows"],
            ] as [keyof DQThresholds, string][]).map(([k, label]) => (
              <div className="field" key={k}>
                <label htmlFor={`th-${k}`}>{label}</label>
                <input id={`th-${k}`} type="number" step="any" min={0} value={state.dq.thresholds[k]}
                  onChange={(e) => patch({ dq: { ...state.dq, thresholds: { ...state.dq.thresholds, [k]: Number(e.target.value) } } })} />
              </div>
            ))}
          </div>
        </Card>
        <Card title="Governance">
          <div className="toggle-list">
            <Toggle label="PII classification" help="Name rules + regex sampling" checked={state.governance.pii_classification} onChange={(v) => patch({ governance: { ...state.governance, pii_classification: v } })} />
            <Toggle label="Mask PII before load" checked={state.governance.masking} disabled={!state.governance.pii_classification} onChange={(v) => patch({ governance: { ...state.governance, masking: v } })} />
            <div className="field indent">
              <label htmlFor="mask">Default masking strategy <Help text="hash = salted SHA-256 hex; partial keeps a prefix; nullify drops values" /></label>
              <select id="mask" value={state.governance.default_masking_strategy} disabled={!state.governance.masking}
                onChange={(e) => patch({ governance: { ...state.governance, default_masking_strategy: e.target.value as MaskingStrategy } })}>
                {["hash", "partial", "nullify", "none"].map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            <Toggle label="Encryption at rest" help={m?.governance.encryption_at_rest} checked={state.governance.encryption_at_rest} onChange={(v) => patch({ governance: { ...state.governance, encryption_at_rest: v } })} />
            <Toggle label="Encryption in transit" help={m?.governance.encryption_in_transit} checked={state.governance.encryption_in_transit} onChange={(v) => patch({ governance: { ...state.governance, encryption_in_transit: v } })} />
            <Toggle label="Access roles script" help={m?.governance.access_model} checked={state.governance.access_roles} onChange={(v) => patch({ governance: { ...state.governance, access_roles: v } })} />
          </div>
        </Card>
        <Card title="Run options">
          <div className="form-grid form-grid-tight">
            <div className="field"><label htmlFor="batch">Batch rows</label><input id="batch" type="number" min={1000} step={1000} value={state.options.batch_rows} onChange={(e) => patch({ options: { ...state.options, batch_rows: Number(e.target.value) } })} /></div>
            <div className="field"><label htmlFor="par">Parallel tables</label><input id="par" type="number" min={1} max={16} value={state.options.parallelism} onChange={(e) => patch({ options: { ...state.options, parallelism: Number(e.target.value) } })} /></div>
            <div className="field"><label htmlFor="att">Max attempts</label><input id="att" type="number" min={1} max={10} value={state.options.max_attempts} onChange={(e) => patch({ options: { ...state.options, max_attempts: Number(e.target.value) } })} /></div>
          </div>
          <h4 className="section-title mt">Demo</h4>
          <Toggle label="Inject transient failure" help="Make a table fail at a stage for the first N attempts (demonstrates retry/resume)" checked={state.inject.enabled} onChange={(enabled) => patch({ inject: { ...state.inject, enabled } })} />
          {state.inject.enabled && (
            <div className="form-grid form-grid-tight mt-s">
              <div className="field"><label htmlFor="inj-t">Table</label>
                <select id="inj-t" value={state.inject.table} onChange={(e) => patch({ inject: { ...state.inject, table: e.target.value } })}>
                  {selected.map((t) => <option key={t}>{t}</option>)}
                </select></div>
              <div className="field"><label htmlFor="inj-s">Stage</label>
                <select id="inj-s" value={state.inject.stage} onChange={(e) => patch({ inject: { ...state.inject, stage: e.target.value as FailureStage } })}>
                  {["extracting", "transforming", "loading", "validating"].map((s) => <option key={s}>{s}</option>)}
                </select></div>
              <div className="field"><label htmlFor="inj-n">Fail first N attempts <Help text="N ≥ max attempts makes the table fail the run until you press Retry" /></label>
                <input id="inj-n" type="number" min={1} max={10} value={state.inject.times} onChange={(e) => patch({ inject: { ...state.inject, times: Number(e.target.value) } })} /></div>
            </div>
          )}
        </Card>
      </div>

      <div className="action-bar">
        <div className="small">
          <strong>{selected.length}</strong> tables · <strong>{fmtCompact(selectedRows)}</strong> rows · {state.database} → <strong>{m?.display_name ?? "…"}</strong> ({state.targetMode})
          {problems.length > 0 && <span className="text-warn"> — {problems[0]}</span>}
        </div>
        {submitError && <span className="text-bad small">{submitError}</span>}
        <button className="btn btn-primary" disabled={!m || problems.length > 0 || submitting} onClick={generate}>
          {submitting ? "Generating…" : "Generate plan →"}
        </button>
      </div>
    </div>
  );
}

function tableOptsSummary(m: TargetMeta, v: Record<string, unknown> | undefined) {
  if (!v) return "";
  return Object.entries(visibleValues(fieldsInScope(m.config_fields, "table"), v))
    .filter(([, x]) => x !== false && !(Array.isArray(x) && !x.length))
    .map(([k, x]) => `${k}=${Array.isArray(x) ? x.join("+") : String(x)}`)
    .join(" · ");
}

function SourcePanel({ conn, databases, database, onDatabase, tablesFound }: {
  conn: ReturnType<typeof useAsync<SourceConnection>>;
  databases: string[]; database: string; onDatabase: (d: string) => void; tablesFound?: number;
}) {
  const [test, setTest] = useState<ConnectionTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setTesting(true);
    setErr(null);
    try {
      setTest(await api.testSource());
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setTesting(false);
    }
  };
  return (
    <Card title={<span className="row gap-s">Source <Badge tone="accent">Teradata</Badge></span>} actions={<button className="btn btn-sm" onClick={run} disabled={testing}>{testing ? "Testing…" : "Test connection"}</button>}>
      {conn.error ? <ErrorBox error={conn.error} onRetry={conn.reload} /> : !conn.data ? <Spinner /> : (
        <dl className="kv">
          <dt>Mode</dt><dd><Badge tone={conn.data.mode === "real" ? "ok" : "info"}>{conn.data.mode}</Badge> {conn.data.mode === "emulated" && <span className="small muted">PostgreSQL + emulated DBC dictionary</span>}</dd>
          <dt>Host</dt><dd className="mono">{conn.data.host}</dd>
          <dt>Database</dt>
          <dd>
            <select aria-label="Source database" value={database} onChange={(e) => onDatabase(e.target.value)}>
              {(databases.length ? databases : [database]).map((d) => <option key={d}>{d}</option>)}
            </select>
          </dd>
          <dt>Tables found</dt><dd><strong>{tablesFound ?? "…"}</strong></dd>
          <dt>Connection</dt>
          <dd>
            {err ? <span className="text-bad small">{err}</span> : test ? (
              <span className="row gap-s wrap">
                <Badge tone={test.ok ? "ok" : "bad"}>{test.ok ? "OK" : "FAILED"}</Badge>
                {test.latency_ms != null && <span className="mono small">{test.latency_ms.toFixed(1)} ms</span>}
                {test.server_version && <span className="small">{test.server_version}</span>}
                <span className="small muted">{test.message}</span>
              </span>
            ) : <span className="small muted">not tested</span>}
          </dd>
        </dl>
      )}
    </Card>
  );
}

function TargetConnection({ meta, values, onChange }: { meta: TargetMeta; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const [res, setRes] = useState<ConnectionTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const test = async () => {
    setBusy(true);
    try {
      setRes(await api.testTarget(meta.id, "real", visibleValues(meta.connection_fields, values)));
    } catch (e) {
      setRes({ ok: false, mode: "real", message: errMsg(e), details: {} });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="subpanel mt">
      <div className="row space-between">
        <h4 className="section-title">Real-mode connection</h4>
        <button className="btn btn-xs" disabled={busy} onClick={test}>{busy ? "Testing…" : "Test target"}</button>
      </div>
      <ConfigForm idPrefix="conn" fields={meta.connection_fields} values={values} onChange={onChange} />
      {res && <div className={`alert mt-s small ${res.ok ? "alert-ok" : "alert-bad"}`}>{res.ok ? "Connected" : "Failed"}: {res.message} {res.latency_ms != null && `(${res.latency_ms.toFixed(0)} ms)`}</div>}
    </div>
  );
}
