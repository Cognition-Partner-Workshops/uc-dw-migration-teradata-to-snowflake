import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { ChecklistItem, Conversion, Formats, Job, TargetId } from '../api'
import { Badge, Card } from './common'
import { short } from './format'

interface Props {
  job: Job
  target: TargetId
  formats: Formats | null
  onNext: () => void
}

const REPORTS = ['review_checklist.md', 'conversion_report.md', 'mapping_report.md', 'mapping_report.csv', 'data_loading_instructions.md']

const CATEGORY: Record<ChecklistItem['category'], string> = {
  complete: 'Complete',
  verify: 'Verify',
  deploy: 'Before deploy',
  test: 'Test',
}

function useTicks(key: string): [Set<number>, (i: number) => void] {
  const [ticks, setTicks] = useState<Set<number>>(new Set())
  useEffect(() => {
    try {
      setTicks(new Set(JSON.parse(localStorage.getItem(key) ?? '[]') as number[]))
    } catch {
      setTicks(new Set())
    }
  }, [key])
  const toggle = (i: number) => {
    const next = new Set(ticks)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    setTicks(next)
    localStorage.setItem(key, JSON.stringify([...next]))
  }
  return [ticks, toggle]
}

function ReviewChecklist({ jobId, conv }: { jobId: string; conv: Conversion }) {
  const items = conv.checklist ?? []
  const [ticks, toggle] = useTicks(`review:${jobId}:${conv.target}:${conv.object_id}`)
  if (!items.length) return null
  const done = items.filter((_, i) => ticks.has(i)).length
  return (
    <div className="checklist">
      <div className="checklist-head">
        <strong>What needs review</strong>
        <span className={`badge ${done === items.length ? 'passed' : 'manual_review'}`}>
          {done} of {items.length} checked
        </span>
      </div>
      {(['complete', 'verify', 'deploy', 'test'] as const).map((cat) => {
        const rows = items.map((it, i) => ({ it, i })).filter(({ it }) => it.category === cat)
        if (!rows.length) return null
        return (
          <div key={cat} className="checklist-group">
            <div className="checklist-cat">{CATEGORY[cat]}</div>
            {rows.map(({ it, i }) => (
              <label key={i} className={ticks.has(i) ? 'done' : ''}>
                <input type="checkbox" checked={ticks.has(i)} onChange={() => toggle(i)} /> {it.text}
              </label>
            ))}
          </div>
        )
      })}
    </div>
  )
}

export default function OutputsStep({ job, target, formats, onNext }: Props) {
  const a = job.analysis!
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
  const toReview = convs.filter((c) => c.checklist?.length).length

  return (
    <>
      <div className="tabs">
        <span className="target-label">Target: {formats?.targets[target] ?? target}</span>
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
          <Card title="Objects" extra={<span className="small muted">{toReview} of {convs.length} need review</span>}>
            <ul className="objlist">
              {convs.map((c) => (
                <li key={c.object_id} className={c.object_id === selected ? 'active' : ''} onClick={() => setSelected(c.object_id)}>
                  <span className="mono">{short(c.object_id)}</span>
                  <span className="objbadges">
                    {!!c.checklist?.length && <span className="badge review" title={`${c.checklist.length} item(s) to review`}>Review · {c.checklist.length}</span>}
                    <Badge status={c.status} />
                  </span>
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
              <ReviewChecklist jobId={job.id} conv={conv} />
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
