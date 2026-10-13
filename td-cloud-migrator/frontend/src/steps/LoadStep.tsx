import type { Formats, Job, TargetId } from '../api'
import { Badge, Card, Stat } from './common'
import { short } from './format'

interface Props {
  job: Job
  target: TargetId
  formats: Formats | null
  busy: boolean
  onLoad: () => void
}

export default function LoadStep({ job, target, formats, busy, onLoad }: Props) {
  const loads = Object.values(job.loads).filter((l) => l.target === target)
  const label = formats?.targets[target] ?? target
  return (
    <>
      <Card title="Create destination tables and load data">
        <p className="muted">
          The target is simulated by a local DuckDB warehouse using its converted column types. Tables are created in dependency order, validated rows are loaded, and
          the result is reconciled against the source files (row counts, NULL counts, numeric sums and string-length checksums). Converted views are then created on the loaded data.
        </p>
        <div className="run-row">
          <span className="target-label">Target: {label}</span>
          <span className="spacer" />
          <button className="primary" disabled={busy} onClick={onLoad}>
            {loads.length ? 'Re-run load' : `Run simulated load into ${label.split(' (')[0]}`}
          </button>
        </div>
      </Card>
      {loads.map((l) => {
        const loaded = l.tables.reduce((s, t) => s + t.loaded_rows, 0)
        const rejected = l.tables.reduce((s, t) => s + t.rejected_rows, 0)
        const checks = l.tables.reduce((s, t) => s + t.checks_passed, 0)
        const total = l.tables.reduce((s, t) => s + t.checks_total, 0)
        return (
          <Card key={l.target} title={formats?.targets[l.target] ?? l.target} extra={<Badge status={l.status} />}>
            <div className="stats">
              <Stat label="tables created" value={`${l.tables.filter((t) => t.created).length}/${l.tables.length}`} />
              <Stat label="rows loaded" value={loaded.toLocaleString()} tone="good" />
              <Stat label="rows rejected" value={rejected} tone={rejected ? 'warn' : ''} />
              <Stat label="validation checks passed" value={`${checks}/${total}`} tone={checks === total ? 'good' : 'bad'} />
              <Stat label="views created" value={`${l.views.filter((v) => v.created).length}/${l.views.length}`} />
            </div>
            <table>
              <thead>
                <tr><th>Source table</th><th>Target table</th><th>Files</th><th>Source rows</th><th>Rejected</th><th>Loaded</th><th>Checks</th><th>Status</th><th>Notes</th></tr>
              </thead>
              <tbody>
                {l.tables.map((t) => (
                  <tr key={t.table_id}>
                    <td className="mono">{short(t.table_id)}</td>
                    <td className="mono small">{t.target_table}</td>
                    <td>{t.files.length}</td>
                    <td>{t.source_rows.toLocaleString()}</td>
                    <td>{t.rejected_rows}</td>
                    <td>{t.loaded_rows.toLocaleString()}</td>
                    <td>{t.checks_total ? `${t.checks_passed}/${t.checks_total}` : '—'}</td>
                    <td><Badge status={t.status} /></td>
                    <td className="small">{t.error ?? (t.failed_checks.join('; ') || (t.status === 'structure_only' ? 'No data file for this table' : '—'))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table>
              <thead>
                <tr><th>View</th><th>Created</th><th>Rows returned</th><th>Notes</th></tr>
              </thead>
              <tbody>
                {l.views.map((v) => (
                  <tr key={v.object_id}>
                    <td className="mono">{v.target_view}</td>
                    <td><Badge status={v.created ? 'passed' : 'failed'}>{v.created ? 'yes' : 'no'}</Badge></td>
                    <td>{v.row_count ?? '—'}</td>
                    <td className="small">{v.error ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      })}
    </>
  )
}
