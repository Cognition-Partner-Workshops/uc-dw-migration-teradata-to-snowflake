import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Formats, Job, TargetId } from '../api'
import { Badge, Card } from './common'
import { short } from './format'

interface Props {
  job: Job
  targets: TargetId[]
  formats: Formats | null
  onNext: () => void
}

const REPORTS = ['conversion_report.md', 'mapping_report.md', 'mapping_report.csv', 'data_loading_instructions.md']

export default function OutputsStep({ job, targets, formats, onNext }: Props) {
  const a = job.analysis!
  const [target, setTarget] = useState<TargetId>(targets[0])
  const [view, setView] = useState<'sql' | 'reports' | 'scripts'>('sql')
  const [selected, setSelected] = useState<string>(a.create_order[0])
  const [files, setFiles] = useState<Record<string, string>>({})
  const [doc, setDoc] = useState(REPORTS[0])

  useEffect(() => {
    api.outputs(job.id).then(setFiles).catch(() => setFiles({}))
  }, [job])

  const convs = useMemo(() => a.conversions.filter((c) => c.target === target), [a, target])
  const conv = convs.find((c) => c.object_id === selected)
  const scripts = Object.keys(files).filter((f) => f.startsWith(`${target}/load/`) || f === `${target}/deploy_all.sql`)
  const mapping = a.type_mappings[target]?.[selected]

  return (
    <>
      <div className="tabs">
        {targets.map((t) => (
          <button key={t} className={t === target ? 'active' : ''} onClick={() => setTarget(t)}>
            {formats?.targets[t] ?? t}
          </button>
        ))}
        <span className="spacer" />
        <a className="button primary" href={api.bundleUrl(job.id)}>
          Download output bundle (.zip)
        </a>
      </div>
      <div className="tabs secondary">
        <button className={view === 'sql' ? 'active' : ''} onClick={() => setView('sql')}>Converted SQL</button>
        <button className={view === 'scripts' ? 'active' : ''} onClick={() => setView('scripts')}>Deploy &amp; load scripts</button>
        <button className={view === 'reports' ? 'active' : ''} onClick={() => setView('reports')}>Reports</button>
      </div>
      {view === 'sql' && (
        <div className="split">
          <Card title="Objects">
            <ul className="objlist">
              {convs.map((c) => (
                <li key={c.object_id} className={c.object_id === selected ? 'active' : ''} onClick={() => setSelected(c.object_id)}>
                  <span className="mono">{short(c.object_id)}</span>
                  <Badge status={c.status} />
                </li>
              ))}
            </ul>
          </Card>
          {conv && (
            <Card title={short(conv.object_id)} extra={<Badge status={conv.status} />}>
              {conv.reason && <div className="alert warn">{conv.reason}</div>}
              <div className="grid2 tight">
                <div>
                  <strong>Rules applied</strong>
                  <ul className="small">{conv.rules.length ? conv.rules.map((r) => <li key={r}>{r}</li>) : <li className="muted">none</li>}</ul>
                </div>
                <div>
                  <strong>Warnings</strong>
                  <ul className="small">{conv.warnings.length ? conv.warnings.map((w) => <li key={w}>{w}</li>) : <li className="muted">none</li>}</ul>
                </div>
              </div>
              <pre className="code">{conv.sql}</pre>
              {mapping && (
                <details>
                  <summary>Column type mapping ({mapping.length} columns)</summary>
                  <table>
                    <thead>
                      <tr><th>Column</th><th>Teradata</th><th>{target}</th><th>Note</th></tr>
                    </thead>
                    <tbody>
                      {mapping.map((m) => (
                        <tr key={m.column}>
                          <td className="mono">{m.column}</td>
                          <td className="mono small">{m.td_type}</td>
                          <td className="mono small">{m.target_type}</td>
                          <td className="small">{m.lossy && <Badge status="manual_review">lossy</Badge>} {m.note}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
            </Card>
          )}
        </div>
      )}
      {view === 'scripts' && (
        <>
          {scripts.map((f) => (
            <Card key={f} title={f}>
              <pre className="code">{files[f]}</pre>
            </Card>
          ))}
        </>
      )}
      {view === 'reports' && (
        <Card title="Reports" extra={
          <select value={doc} onChange={(e) => setDoc(e.target.value)}>
            {REPORTS.map((r) => <option key={r}>{r}</option>)}
          </select>
        }>
          <pre className="code doc">{files[doc] ?? 'Loading…'}</pre>
        </Card>
      )}
      <div className="actions">
        <button className="primary" onClick={onNext}>Load into Cloud (simulated) →</button>
      </div>
    </>
  )
}
