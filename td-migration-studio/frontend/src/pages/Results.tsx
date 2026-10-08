import { Fragment, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { RejectsPage, TableReconciliation } from "../api/types";
import { Badge, Card, Empty, ErrorBox, Spinner, Stat, statusTone } from "../components/ui";
import { download, errMsg, fmtBytes, fmtCompact, fmtDateTime, fmtDuration, fmtInt } from "../lib/format";
import { navigate, useAsync } from "../lib/hooks";

export function Results({ runId }: { runId: string }) {
  const { data: r, error, loading, reload } = useAsync(() => api.report(runId), [runId]);
  const [open, setOpen] = useState<string | null>(null);
  const [log, setLog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState<string | null>(null);

  if (loading && !r) return <div className="page"><Spinner label="Loading reconciliation report…" /></div>;
  if (error || !r)
    return (
      <div className="page">
        <ErrorBox error={error ?? "No report"} onRetry={reload} />
        <button className="btn mt" onClick={() => navigate(`/runs/${runId}`)}>← Back to run monitor</button>
      </div>
    );

  const t = r.totals;
  const chart = r.tables.map((x) => ({ table: x.table, source: x.source_rows, target: x.target_rows, rejected: x.rejected_rows }));
  const retry = async () => {
    setBusy(true);
    try {
      await api.retry(r.run_id, r.tables.filter((x) => x.status === "failed").map((x) => x.table));
      navigate(`/runs/${r.run_id}`);
    } catch (e) {
      setActErr(errMsg(e));
      setBusy(false);
    }
  };
  const csv = async () => {
    try {
      download(`${r.run_id}-reconciliation.csv`, await api.reportCsv(r.run_id), "text/csv");
    } catch (e) {
      setActErr(errMsg(e));
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Reconciliation <span className="mono muted">{r.run_id}</span> <Badge tone={statusTone(r.status)}>{r.status}</Badge></h2>
          <div className="small muted">{r.target_display_name} ({r.target_mode}) · {fmtDateTime(r.started_at)} → {fmtDateTime(r.finished_at)} · plan <a className="mono" href={`#/plans/${r.plan_id}`}>{r.plan_id}</a></div>
        </div>
        <div className="row gap-s">
          {actErr && <span className="text-bad small">{actErr}</span>}
          {t.failed > 0 && <button className="btn" disabled={busy} onClick={retry}>↻ Retry failed ({t.failed})</button>}
          <button className="btn" onClick={csv}>⤓ CSV</button>
          <button className="btn" onClick={() => download(`${r.run_id}-report.json`, JSON.stringify(r, null, 2), "application/json")}>⤓ JSON</button>
          <button className="btn" onClick={() => navigate(`/runs/${r.run_id}`)}>Run log</button>
        </div>
      </div>

      <div className="stats">
        <Stat label="Status" value={<Badge tone={statusTone(r.status)}>{r.status.toUpperCase()}</Badge>} sub={r.target_display_name} />
        <Stat label="Tables passed" value={`${t.passed}/${t.tables}`} tone={t.failed ? "bad" : "ok"} sub={t.failed ? `${t.failed} failed` : "all passed"} />
        <Stat label="Rows moved" value={fmtCompact(t.rows_loaded)} sub={`of ${fmtInt(t.rows_source)} source`} />
        <Stat label="Rejected rows" value={fmtInt(t.rows_rejected)} tone={t.rows_rejected ? "warn" : "ok"} sub={`max ${r.thresholds.max_rejected_rows_pct}% allowed`} />
        <Stat label="Time taken" value={fmtDuration(t.duration_s)} sub={`${fmtBytes(t.bytes_staged)} staged`} />
        <Stat label="Throughput" value={`${fmtCompact(t.throughput_rows_per_s)}/s`} sub="rows/second" />
        <Stat label="Checks passed" value={`${t.checks_passed}/${t.checks_total}`} tone={t.checks_passed === t.checks_total ? "ok" : "bad"} />
      </div>

      <Card title="Source vs target rows per table" actions={<label className="chip-toggle"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> Log scale</label>}>
        <div style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 8, right: 16, bottom: 64, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="table" angle={-25} textAnchor="end" interval={0} tick={{ fontSize: 10 }} />
              <YAxis scale={log ? "log" : "auto"} domain={log ? [1, "auto"] : [0, "auto"]} allowDataOverflow tickFormatter={(v: number) => fmtCompact(v)} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => fmtInt(v)} />
              <Legend verticalAlign="top" height={24} />
              <Bar dataKey="source" name="Source rows" fill="#94a3b8" />
              <Bar dataKey="target" name="Target rows" fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Per-table reconciliation" pad={false}>
        <div className="table-wrap">
          <table className="grid">
            <thead><tr><th style={{ width: 24 }} /><th>Table</th><th className="right">Source rows</th><th className="right">Target rows</th><th className="right">Rejected</th><th>Checksum (source / target)</th><th className="right">Checks</th><th className="right">Duration</th><th>Status</th></tr></thead>
            <tbody>
              {r.tables.map((x) => {
                const ok = x.checks.filter((c) => c.passed).length;
                return (
                  <Fragment key={x.table}>
                    <tr className={`clickable ${x.status === "failed" ? "row-error" : ""}`} onClick={() => setOpen(open === x.table ? null : x.table)}>
                      <td>{open === x.table ? "▾" : "▸"}</td>
                      <td><div className="mono">{x.table}</div><div className="small muted">{x.target_table}</div></td>
                      <td className="right mono">{fmtInt(x.source_rows)}</td>
                      <td className="right mono">{fmtInt(x.target_rows)}</td>
                      <td className={`right mono ${x.rejected_rows ? "text-warn" : ""}`}>{fmtInt(x.rejected_rows)}</td>
                      <td className="mono small">
                        {x.checksum_match == null ? <span className="muted">—</span> : (
                          <span className="row gap-s"><span className={x.checksum_match ? "text-ok" : "text-bad"}>{x.checksum_match ? "✔" : "✘"}</span>{x.source_checksum?.slice(0, 12)} / {x.target_checksum?.slice(0, 12)}</span>
                        )}
                      </td>
                      <td className="right"><Badge tone={ok === x.checks.length ? "ok" : "bad"}>{ok}/{x.checks.length}</Badge></td>
                      <td className="right small">{fmtDuration(x.duration_s)}</td>
                      <td><Badge tone={statusTone(x.status)}>{x.status}</Badge></td>
                    </tr>
                    {open === x.table && <tr className="drill"><td /><td colSpan={8}><Drill runId={r.run_id} t={x} /></td></tr>}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function Drill({ runId, t }: { runId: string; t: TableReconciliation }) {
  const rejects = useAsync<RejectsPage>(
    () => (t.rejected_rows ? api.rejects(runId, t.table) : Promise.resolve({ rows: t.rejects_sample, total: 0 })),
    [runId, t.table],
  );
  const rows = rejects.data?.rows.length ? rejects.data.rows : t.rejects_sample;
  const cols = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div className="drill-body">
      <h4 className="section-title">Checks ({t.checks.length})</h4>
      {t.checks.length === 0 ? <Empty>No checks recorded.</Empty> : (
        <table className="grid grid-inner">
          <thead><tr><th>Check</th><th>Column / key</th><th className="right">Source</th><th className="right">Target</th><th className="right">Diff</th><th>Threshold</th><th>Result</th><th>Detail</th></tr></thead>
          <tbody>
            {t.checks.map((c, i) => (
              <tr key={i} className={c.passed ? "" : "row-error"}>
                <td className="mono small">{c.name}</td><td className="mono small">{c.column ?? "—"}</td>
                <td className="right mono small">{c.source_value ?? "—"}</td><td className="right mono small">{c.target_value ?? "—"}</td>
                <td className="right mono small">{c.diff ?? "—"}</td><td className="small">{c.threshold ?? "—"}</td>
                <td><Badge tone={c.passed ? "ok" : "bad"}>{c.passed ? "pass" : "fail"}</Badge></td><td className="small muted">{c.detail ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h4 className="section-title mt">Rejected rows sample {rejects.data?.total ? <span className="muted small">({fmtInt(rejects.data.total)} total)</span> : null}</h4>
      {rejects.loading ? <Spinner /> : rejects.error ? <ErrorBox error={rejects.error} /> : rows.length === 0 ? <Empty>No rejected rows.</Empty> : (
        <div className="table-wrap">
          <table className="grid grid-inner">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{rows.map((row, i) => <tr key={i}>{cols.map((c) => <td key={c} className="mono small">{String(row[c] ?? "")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
