import { useState } from "react";
import { api } from "../api/client";
import type { ColumnOverride, MigrationPlan } from "../api/types";
import { CodeBlock } from "../components/CodeBlock";
import { MappingTable, type MappingRow } from "../components/MappingTable";
import { Badge, Card, Empty, ErrorBox, Spinner, Stat, Tabs, type Tone } from "../components/ui";
import { errMsg, fmtCompact, fmtDateTime } from "../lib/format";
import { navigate, useAsync } from "../lib/hooks";

type Tab = "mapping" | "tables" | "warnings" | "governance";
const SEV: Record<string, Tone> = { info: "info", warning: "warn", error: "bad" };

export function PlanReview({ planId }: { planId: string }) {
  const { data: plan, error, loading, reload, setData } = useAsync(() => api.plan(planId), [planId]);
  const [tab, setTab] = useState<Tab>("mapping");
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  if (error) return <div className="page"><ErrorBox error={error} onRetry={reload} /></div>;
  if (loading && !plan) return <div className="page"><Spinner label="Loading plan…" /></div>;
  if (!plan) return null;

  const s = plan.summary as Record<string, number>;
  const rows: MappingRow[] = plan.tables.flatMap((t) => t.columns.map((col) => ({ table: t.source.name, col })));
  const errors = plan.warnings.filter((w) => w.severity === "error").length;
  const editable = plan.status === "draft";

  const override = async (o: ColumnOverride) => setData(await api.overrides(plan.id, [o]));
  const approveAndRun = async () => {
    setBusy(true);
    setActionErr(null);
    try {
      if (plan.status !== "approved") setData(await api.approve(plan.id));
      const run = await api.createRun(plan.id);
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setActionErr(errMsg(e));
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Migration plan <span className="mono muted">{plan.id}</span></h2>
          <div className="small muted">
            {plan.request.source_database} → {plan.target.display_name} ({plan.request.target_mode}) · created {fmtDateTime(plan.created_at)} ·{" "}
            <Badge tone={plan.status === "approved" ? "ok" : "muted"}>{plan.status}</Badge>
          </div>
        </div>
      </div>
      <div className="stats">
        <Stat label="Tables" value={s.tables ?? plan.tables.length} />
        <Stat label="Columns" value={s.columns ?? rows.length} />
        <Stat label="Est. rows" value={fmtCompact(s.est_rows)} />
        <Stat label="Lossy columns" value={s.lossy_columns ?? 0} tone={(s.lossy_columns ?? 0) > 0 ? "warn" : "ok"} sub="review conversions" />
        <Stat label="PII columns" value={s.pii_columns ?? 0} tone="info" sub={s.masked_columns != null ? `${s.masked_columns} masked` : undefined} />
        <Stat label="Warnings" value={plan.warnings.length} tone={errors ? "bad" : plan.warnings.length ? "warn" : "ok"} sub={errors ? `${errors} error(s)` : undefined} />
      </div>

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "mapping", label: <>Type mapping <Badge tone="warn">{s.lossy_columns ?? 0} lossy</Badge></> },
        { id: "tables", label: <>Tables & DDL <Badge>{plan.tables.length}</Badge></> },
        { id: "warnings", label: <>Warnings <Badge tone={errors ? "bad" : "warn"}>{plan.warnings.length}</Badge></> },
        { id: "governance", label: "Governance" },
      ]} />

      {tab === "mapping" && (
        <Card title={`Teradata → ${plan.target.display_name} type mapping`} actions={editable ? <span className="small muted">Edit a row to override target type / masking</span> : <Badge tone="ok">approved — read only</Badge>}>
          <MappingTable rows={rows} showTable editable={editable} onOverride={override} />
        </Card>
      )}
      {tab === "tables" && <TablesAccordion plan={plan} editable={editable} onOverride={override} />}
      {tab === "warnings" && (
        <Card title="Warnings" pad={false}>
          {plan.warnings.length === 0 ? <Empty>No warnings — every column maps exactly.</Empty> : (
            <table className="grid">
              <thead><tr><th style={{ width: 90 }}>Severity</th><th>Table</th><th>Column</th><th>Message</th></tr></thead>
              <tbody>
                {plan.warnings.map((w, i) => (
                  <tr key={i} className={`row-${w.severity}`}><td><Badge tone={SEV[w.severity]}>{w.severity}</Badge></td><td className="mono small">{w.table ?? "—"}</td><td className="mono small">{w.column ?? "—"}</td><td>{w.message}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {tab === "governance" && <Governance plan={plan} />}

      <div className="action-bar">
        <button className="btn" onClick={() => navigate("/")}>← Back to planner</button>
        <div className="small grow-right">{errors > 0 && <span className="text-bad">{errors} blocking error(s) — fix in the planner or override</span>}{actionErr && <span className="text-bad"> {actionErr}</span>}</div>
        <button className="btn btn-primary" disabled={busy || errors > 0} onClick={approveAndRun}>{busy ? "Starting…" : plan.status === "approved" ? "Run again →" : "Approve & run →"}</button>
      </div>
    </div>
  );
}

function TablesAccordion({ plan, editable, onOverride }: { plan: MigrationPlan; editable: boolean; onOverride: (o: ColumnOverride) => Promise<void> }) {
  return (
    <div className="accordion accordion-lg">
      {plan.tables.map((t, i) => {
        const lossy = t.columns.filter((c) => c.mapping.lossy).length;
        const pii = t.columns.filter((c) => c.pii).length;
        const warn = plan.warnings.filter((w) => w.table === t.source.name).length;
        return (
          <details key={t.source.name} open={i === 0}>
            <summary>
              <span className="mono strong">{t.source.name}</span>
              <span className="muted small">→ {t.target_container}.{t.target_table}</span>
              <span className="row gap-s grow-right">
                <Badge>{t.columns.length} cols</Badge>
                <Badge>{fmtCompact(t.estimated_rows)} rows</Badge>
                {lossy > 0 && <Badge tone="warn">{lossy} lossy</Badge>}
                {pii > 0 && <Badge tone="accent">{pii} PII</Badge>}
                {warn > 0 && <Badge tone="warn">{warn} warnings</Badge>}
              </span>
            </summary>
            <div className="details-body">
              <div className="grid-ddl">
                <CodeBlock title={`Native ${plan.target.display_name} DDL`} code={t.ddl} maxHeight={320} />
                <div>
                  <h4 className="section-title">Target options</h4>
                  <dl className="kv kv-compact">
                    <dt>load_method</dt><dd className="mono">{t.load_method ?? "—"}</dd>
                    {Object.entries(t.target_options).filter(([k]) => !k.startsWith("__") && k !== "load_method").map(([k, v]) => (
                      <FragmentKV key={k} k={k} v={Array.isArray(v) ? (v.length ? v.join(", ") : "—") : String(v)} />
                    ))}
                  </dl>
                  <h4 className="section-title mt">Source</h4>
                  <dl className="kv kv-compact">
                    <dt>kind</dt><dd>{t.source.kind}</dd>
                    <dt>primary index</dt><dd className="mono">{t.source.primary_index_unique ? "UPI" : "NUPI"} ({t.source.primary_index.join(", ")})</dd>
                    {t.source.partition_expression && <><dt>PPI</dt><dd className="mono small">{t.source.partition_expression}</dd></>}
                    <dt>unique keys</dt><dd className="mono small">{t.source.unique_keys.map((k) => `(${k.join(", ")})`).join(" ") || "—"}</dd>
                    <dt>soft RI</dt><dd className="mono small">{t.source.foreign_keys.map((f) => `${f.columns.join(",")}→${f.ref_table}`).join("; ") || "—"}</dd>
                  </dl>
                </div>
              </div>
              <MappingTable rows={t.columns.map((col) => ({ table: t.source.name, col }))} editable={editable} onOverride={onOverride} />
            </div>
          </details>
        );
      })}
    </div>
  );
}

const FragmentKV = ({ k, v }: { k: string; v: string }) => (
  <>
    <dt>{k}</dt>
    <dd className="mono">{v}</dd>
  </>
);

function Governance({ plan }: { plan: MigrationPlan }) {
  const g = plan.request.governance;
  const masked = plan.tables.flatMap((t) => t.columns.filter((c) => c.pii).map((c) => ({ t: t.source.name, c })));
  const labels: Record<string, string> = { encryption_at_rest: "Encryption at rest", encryption_in_transit: "Encryption in transit", access_model: "Access model", masking: "Masking" };
  return (
    <div className="grid-2">
      <div className="stack">
        <Card title="Controls">
          <div className="row gap-s wrap mb-s">
            {Object.entries(g).filter(([, v]) => typeof v === "boolean").map(([k, v]) => <Badge key={k} tone={v ? "ok" : "muted"}>{v ? "✓" : "✕"} {k.replace(/_/g, " ")}</Badge>)}
          </div>
          {Object.keys(plan.governance_notes).length === 0 ? <Empty>No governance notes.</Empty> : (
            <dl className="kv">{Object.entries(plan.governance_notes).map(([k, v]) => <FragmentKV key={k} k={labels[k] ?? k} v={v} />)}</dl>
          )}
        </Card>
        <Card title={`PII columns (${masked.length})`} pad={false}>
          {masked.length === 0 ? <Empty>No PII detected{g.pii_classification ? "" : " (classification disabled)"}.</Empty> : (
            <table className="grid">
              <thead><tr><th>Table</th><th>Column</th><th>Category</th><th className="right">Confidence</th><th>Masking</th></tr></thead>
              <tbody>{masked.map(({ t, c }) => (
                <tr key={t + c.source.name}><td className="mono small">{t}</td><td className="mono">{c.source.name}</td><td><Badge tone="accent">{c.pii!.category}</Badge> <span className="small muted">{c.pii!.reason}</span></td><td className="right">{Math.round(c.pii!.confidence * 100)}%</td><td>{c.pii!.masking}</td></tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      </div>
      <Card title="Access / role script">
        {plan.access_script ? <CodeBlock title={`${plan.target.display_name} access script`} code={plan.access_script} maxHeight={520} /> : <Empty>Access-role script disabled or not provided for this target.</Empty>}
      </Card>
    </div>
  );
}
