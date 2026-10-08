import { useEffect, useRef, useState } from "react";
import { api, subscribeRunEvents, type StreamStatus } from "../api/client";
import { TERMINAL_STATUSES, type Run, type RunEvent } from "../api/types";
import { LogConsole } from "../components/LogConsole";
import { StagePipeline } from "../components/StagePipeline";
import { Badge, Card, ErrorBox, Spinner, Stat, statusTone } from "../components/ui";
import { errMsg, fmtCompact, fmtDuration, fmtInt } from "../lib/format";
import { navigate, useNow } from "../lib/hooks";

export function RunMonitor({ runId }: { runId: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [stream, setStream] = useState<StreamStatus>("connecting");
  const [busy, setBusy] = useState(false);
  const wasActive = useRef(false);
  const refetchPending = useRef(false);

  const refresh = async () => {
    try {
      setRun(await api.run(runId));
      setError(null);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  useEffect(() => {
    setEvents([]);
    void refresh();
    const off = subscribeRunEvents(runId, 0, (e) => {
      setEvents((prev) => (prev.length && prev[prev.length - 1].seq >= e.seq ? prev : [...prev, e]));
      if (e.kind !== "log" && !refetchPending.current) {
        refetchPending.current = true;
        setTimeout(() => { refetchPending.current = false; void refresh(); }, 300);
      }
    }, setStream);
    const poll = setInterval(refresh, 2000);
    return () => { off(); clearInterval(poll); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const terminal = run ? TERMINAL_STATUSES.includes(run.status) : false;
  const now = useNow(500, !terminal);
  const failed = run?.objects.filter((o) => o.stage === "failed") ?? [];

  // Auto-navigate to results when a run we watched finishes cleanly.
  useEffect(() => {
    if (!run) return;
    if (!terminal) wasActive.current = true;
    else if (wasActive.current && run.status === "succeeded") {
      const t = setTimeout(() => navigate(`/runs/${run.id}/results`), 1500);
      return () => clearTimeout(t);
    }
  }, [run, terminal]);

  if (error && !run) return <div className="page"><ErrorBox error={error} onRetry={refresh} /></div>;
  if (!run) return <div className="page"><Spinner label="Loading run…" /></div>;

  const start = run.started_at ? Date.parse(run.started_at) : Date.parse(run.created_at);
  const end = run.finished_at ? Date.parse(run.finished_at) : now;
  const elapsed = Math.max(0, (end - start) / 1000);
  const loaded = run.objects.reduce((a, o) => a + o.rows_loaded, 0);
  const extracted = run.objects.reduce((a, o) => a + o.rows_extracted, 0);
  const rejected = run.objects.reduce((a, o) => a + o.rows_rejected, 0);
  const passed = run.objects.filter((o) => o.stage === "passed").length;

  const act = async (fn: () => Promise<Run>) => {
    setBusy(true);
    try {
      wasActive.current = true;
      setRun(await fn());
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Run <span className="mono muted">{run.id}</span> <Badge tone={statusTone(run.status)}>{run.status}</Badge></h2>
          <div className="small muted">plan <a href={`#/plans/${run.plan_id}`} className="mono">{run.plan_id}</a> · target {run.target_id} ({run.target_mode}){run.resumed_from && ` · resumed from ${run.resumed_from}`}</div>
        </div>
        <div className="row gap-s">
          <button className="btn" disabled={busy || !terminal || failed.length === 0} onClick={() => act(() => api.retry(run.id, failed.map((o) => o.table)))}>↻ Retry failed{failed.length ? ` (${failed.length})` : ""}</button>
          <button className="btn" disabled={busy || !terminal || run.status === "succeeded"} onClick={() => act(() => api.resume(run.id))}>▶ Resume</button>
          <button className="btn btn-primary" disabled={!terminal} onClick={() => navigate(`/runs/${run.id}/results`)}>Results →</button>
        </div>
      </div>

      {error && <ErrorBox error={error} />}
      {terminal && failed.length > 0 && (
        <div className="alert alert-warn">
          Run finished <strong>{run.status}</strong>: {failed.map((o) => o.table).join(", ")} failed after {Math.max(...failed.map((o) => o.attempts))} attempt(s). Use <strong>Retry failed</strong> (restarts from the last durable stage) or view the results.
        </div>
      )}
      {terminal && run.status === "succeeded" && wasActive.current && <div className="alert alert-ok">All tables passed — opening results…</div>}

      <div className="card progress-card">
        <div className="row space-between small">
          <span><strong>{Math.round(run.progress * 100)}%</strong> · {passed}/{run.objects.length} tables passed{failed.length ? ` · ${failed.length} failed` : ""}</span>
          <span className="muted">elapsed {fmtDuration(elapsed)}</span>
        </div>
        <div className="progress"><div className={`progress-bar ${terminal ? (failed.length ? "bar-warn" : "bar-ok") : "bar-run"}`} style={{ width: `${run.progress * 100}%` }} /></div>
        <div className="stats stats-inline">
          <Stat label="Rows extracted" value={fmtCompact(extracted)} />
          <Stat label="Rows loaded" value={fmtCompact(loaded)} />
          <Stat label="Rejected" value={fmtInt(rejected)} tone={rejected ? "warn" : undefined} />
          <Stat label="Throughput" value={`${fmtCompact(elapsed ? loaded / elapsed : 0)}/s`} sub="rows loaded per second" />
        </div>
      </div>

      <Card title="Tables" pad={false}>
        <div className="table-wrap">
          <table className="grid">
            <thead><tr><th>Table</th><th>Pipeline</th><th className="right">Attempts</th><th className="right">Extracted</th><th className="right">Loaded</th><th className="right">Rejected</th><th style={{ width: 140 }}>Progress</th><th>Error</th></tr></thead>
            <tbody>
              {run.objects.map((o) => (
                <tr key={o.table} className={o.stage === "failed" ? "row-error" : ""}>
                  <td><div className="mono">{o.table}</div><div className="small muted">{o.target_table}</div></td>
                  <td><StagePipeline o={o} /></td>
                  <td className="right">{o.attempts > 1 ? <Badge tone="warn">{o.attempts}</Badge> : o.attempts}</td>
                  <td className="right mono">{fmtInt(o.rows_extracted)}</td>
                  <td className="right mono">{fmtInt(o.rows_loaded)}</td>
                  <td className={`right mono ${o.rows_rejected ? "text-warn" : ""}`}>{fmtInt(o.rows_rejected)}</td>
                  <td><div className="progress progress-sm"><div className={`progress-bar ${o.stage === "failed" ? "bar-bad" : o.stage === "passed" ? "bar-ok" : "bar-run"}`} style={{ width: `${o.progress * 100}%` }} /></div></td>
                  <td className="small text-bad error-cell" title={o.error ?? undefined}>{o.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Live log">
        <LogConsole events={events} status={stream} tables={run.objects.map((o) => o.table)} />
      </Card>
    </div>
  );
}
