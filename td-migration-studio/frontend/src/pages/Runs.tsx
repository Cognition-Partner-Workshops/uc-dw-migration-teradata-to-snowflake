import { api } from "../api/client";
import { TERMINAL_STATUSES } from "../api/types";
import { Badge, Card, Empty, ErrorBox, Spinner, statusTone } from "../components/ui";
import { fmtDateTime, fmtDuration, fmtInt } from "../lib/format";
import { navigate, useAsync } from "../lib/hooks";

export function Runs() {
  const { data, error, loading, reload } = useAsync(() => api.runs(), []);
  return (
    <div className="page">
      <div className="page-head">
        <h2>Runs</h2>
        <div className="row gap-s"><button className="btn" onClick={reload}>Refresh</button><button className="btn btn-primary" onClick={() => navigate("/")}>New migration</button></div>
      </div>
      <Card pad={false}>
        {error ? <div className="card-body"><ErrorBox error={error} onRetry={reload} /></div> : loading && !data ? <div className="card-body"><Spinner /></div> : !data?.length ? <Empty>No runs yet — generate and approve a plan to start one.</Empty> : (
          <table className="grid">
            <thead><tr><th>Run</th><th>Status</th><th>Target</th><th>Created</th><th className="right">Tables</th><th className="right">Rows loaded</th><th className="right">Duration</th><th /></tr></thead>
            <tbody>
              {data.map((r) => {
                const done = TERMINAL_STATUSES.includes(r.status);
                const passed = r.objects.filter((o) => o.stage === "passed").length;
                const dur = r.started_at && r.finished_at ? (Date.parse(r.finished_at) - Date.parse(r.started_at)) / 1000 : null;
                return (
                  <tr key={r.id} className="clickable" onClick={() => navigate(done ? `/runs/${r.id}/results` : `/runs/${r.id}`)}>
                    <td className="mono">{r.id}</td>
                    <td><Badge tone={statusTone(r.status)}>{r.status}</Badge></td>
                    <td>{r.target_id} <span className="muted small">({r.target_mode})</span></td>
                    <td className="small">{fmtDateTime(r.created_at)}</td>
                    <td className="right">{passed}/{r.objects.length}</td>
                    <td className="right mono">{fmtInt(r.objects.reduce((a, o) => a + o.rows_loaded, 0))}</td>
                    <td className="right small">{fmtDuration(dur)}</td>
                    <td className="right nowrap">
                      <button className="btn btn-xs" onClick={(e) => { e.stopPropagation(); navigate(`/runs/${r.id}`); }}>Monitor</button>{" "}
                      <button className="btn btn-xs" disabled={!done} onClick={(e) => { e.stopPropagation(); navigate(`/runs/${r.id}/results`); }}>Results</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
