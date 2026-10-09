import { Fragment, useMemo, useState } from 'react'
import type { Formats, Job, TargetId } from '../api'
import { Badge, Card, Stat } from './common'
import { short } from './format'

interface Props {
  job: Job
  formats: Formats | null
  onOverride: (file: string, table: string) => void
  onNext: () => void
}

export default function AnalyseStep({ job, formats, onOverride, onNext }: Props) {
  const a = job.analysis!
  const targets = job.options.targets
  const [open, setOpen] = useState<string | null>(null)
  const [openTable, setOpenTable] = useState<string | null>(null)
  const status = useMemo(() => {
    const m: Record<string, Partial<Record<TargetId, string>>> = {}
    a.conversions.forEach((c) => ((m[c.object_id] ??= {})[c.target] = c.status))
    return m
  }, [a])
  const byType = a.objects.reduce<Record<string, number>>((acc, o) => ({ ...acc, [o.object_type]: (acc[o.object_type] ?? 0) + 1 }), {})
  const tables = a.objects.filter((o) => o.table)
  const objects = new Map(a.objects.map((o) => [o.id, o]))
  const counts = (t: TargetId) => a.conversions.filter((c) => c.target === t).reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }), {})

  return (
    <>
      <div className="stats">
        {Object.entries(byType).map(([k, v]) => (
          <Stat key={k} label={k.replace('_', ' ') + (v > 1 ? 's' : '')} value={v} />
        ))}
        <Stat label="data files" value={a.data.length} />
        <Stat label="rows in data dump" value={a.readiness.reduce((s, r) => s + r.total_rows, 0).toLocaleString()} />
      </div>
      <Card title="Conversion status by target">
        <table>
          <thead>
            <tr>
              <th>Target</th>
              <th>Converted</th>
              <th>Converted with warnings</th>
              <th>Manual review</th>
              <th>Unsupported</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((t) => {
              const c = counts(t)
              return (
                <tr key={t}>
                  <td>{formats?.targets[t] ?? t}</td>
                  <td><Badge status="converted">{c.converted ?? 0}</Badge></td>
                  <td><Badge status="converted_with_warnings">{c.converted_with_warnings ?? 0}</Badge></td>
                  <td><Badge status="manual_review">{c.manual_review ?? 0}</Badge></td>
                  <td><Badge status="unsupported">{c.unsupported ?? 0}</Badge></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
      <Card title="Configuration analysis: objects in create order" extra={<span className="muted">{a.config_files.length} file(s) analysed · click a row for details</span>}>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Object</th>
              <th>Type</th>
              <th>Source</th>
              <th>Depends on</th>
              <th>Teradata features</th>
              {targets.map((t) => (
                <th key={t}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {a.create_order.map((id, i) => {
              const o = objects.get(id)!
              return (
                <Fragment key={id}>
                  <tr className="clickable" onClick={() => setOpen(open === id ? null : id)}>
                    <td>{i + 1}</td>
                    <td className="mono">{o.database ? `${o.database}.${o.name}` : o.name}</td>
                    <td>{o.object_type}</td>
                    <td className="muted small">{o.source_file}</td>
                    <td className="small">{o.dependencies.map((d) => d.split('.').pop()).join(', ') || '—'}</td>
                    <td className="small">{o.table ? `${o.table.kind}, ${o.table.columns.length} cols, PI(${o.table.primary_index.join(', ')})` : o.features.join(', ') || '—'}</td>
                    {targets.map((t) => (
                      <td key={t}>{status[id]?.[t] && <Badge status={status[id][t]!} />}</td>
                    ))}
                  </tr>
                  {open === id && (
                    <tr className="detail">
                      <td colSpan={6 + targets.length}>
                        {o.parse_error && <div className="alert error">{o.parse_error}</div>}
                        {o.table && (
                          <p className="small">
                            Partitioning: {o.table.partition_expression ?? 'none'} · Unique keys: {o.table.unique_keys.map((k) => k.join('+')).join(', ') || 'none'} · {o.table.comment}
                          </p>
                        )}
                        <pre className="code small">{o.sql.slice(0, 4000)}</pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </Card>
      <Card title="Data analysis: files → destination tables" extra={a.manifest && <span className="muted">Manifest: {a.manifest}</span>}>
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Format</th>
              <th>Delimiter</th>
              <th>Header</th>
              <th>Rows</th>
              <th>Cols</th>
              <th>Destination table</th>
              <th>Match</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
            {a.data.map((d) => (
              <tr key={d.path}>
                <td className="mono small">{d.path}</td>
                <td>{d.format}{d.compressed ? ' (gzip)' : ''}</td>
                <td className="mono">{d.delimiter === '\t' ? 'TAB' : (d.delimiter ?? '—')}</td>
                <td>{d.has_header === null ? '—' : d.has_header ? 'yes' : 'no'}</td>
                <td>{d.row_count.toLocaleString()}</td>
                <td>{d.column_count}</td>
                <td>
                  <select value={d.table_id ?? ''} onChange={(e) => onOverride(d.path, e.target.value)}>
                    <option value="">— not mapped —</option>
                    {tables.map((t) => (
                      <option key={t.id} value={t.id}>
                        {short(t.id)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <Badge status={d.match_confidence >= 0.9 ? 'ready' : d.table_id ? 'ready_with_warnings' : 'blocked'}>
                    {d.match_method} {Math.round(d.match_confidence * 100)}%
                  </Badge>
                </td>
                <td className="small">{d.issues.join('; ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card title="Data preparation: table readiness" extra={<span className="muted">click a row for column sourcing and validation</span>}>
        <table>
          <thead>
            <tr>
              <th>Table</th>
              <th>Files</th>
              <th>Rows</th>
              <th>Rejected</th>
              <th>Status</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
            {a.readiness.map((r) => (
              <Fragment key={r.table_id}>
                <tr className="clickable" onClick={() => setOpenTable(openTable === r.table_id ? null : r.table_id)}>
                  <td className="mono">{short(r.table_id)}</td>
                  <td>{r.files.length}</td>
                  <td>{r.total_rows.toLocaleString()}</td>
                  <td>{r.rejected_rows + r.duplicate_rows}</td>
                  <td><Badge status={r.status} /></td>
                  <td className="small">{r.issues.join('; ') || '—'}</td>
                </tr>
                {openTable === r.table_id && (
                  <tr className="detail">
                    <td colSpan={6}>
                      <div className="chips">
                        {r.columns.map((c) => (
                          <span key={c.column} className={`chip ${c.source}`} title={c.samples.join('\n')}>
                            {c.column} · {c.source}
                            {c.parse_errors + c.null_violations + c.length_violations > 0 && ` · ${c.parse_errors + c.null_violations + c.length_violations} bad`}
                          </span>
                        ))}
                      </div>
                      {r.columns.flatMap((c) => c.samples.map((s) => `${c.column}: ${s}`)).map((s) => (
                        <div key={s} className="small mono">{s}</div>
                      ))}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {a.messages.length > 0 && (
          <ul className="small muted">
            {a.messages.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
      </Card>
      <div className="actions">
        <button className="primary" onClick={onNext}>
          View migration outputs →
        </button>
      </div>
    </>
  )
}
