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

type Answer = 'accept' | 'fix' | 'done'
interface ReviewState { a: Record<number, Answer>; n: Record<number, string> }

const SIM_CHECK = 'Load a sample and check nulls'

type Effort = 'Light' | 'Medium' | 'Heavy'
function effortOf(objectType: string | undefined): Effort {
  if (objectType === 'table') return 'Light'
  if (objectType === 'view') return 'Medium'
  return 'Heavy'
}
const EFFORT_HINT: Record<Effort, string> = {
  Light: 'Light review: a few notes to accept or fix. The data checks are covered by Load & validate.',
  Medium: 'Medium review: check the query logic, then compare its results with Teradata.',
  Heavy: 'Heavy review: procedural logic. Check each step and test it in a cloud sandbox before use.',
}

function useReview(key: string): [ReviewState, (i: number, v: Answer | null) => void, (i: number, note: string) => void] {
  const [st, setSt] = useState<ReviewState>({ a: {}, n: {} })
  useEffect(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(key) ?? 'null') as ReviewState | number[] | null
      if (Array.isArray(raw)) setSt({ a: Object.fromEntries(raw.map((i) => [i, 'done' as Answer])), n: {} })
      else setSt(raw && raw.a ? { a: raw.a, n: raw.n ?? {} } : { a: {}, n: {} })
    } catch {
      setSt({ a: {}, n: {} })
    }
  }, [key])
  const save = (next: ReviewState) => {
    setSt(next)
    localStorage.setItem(key, JSON.stringify(next))
  }
  const answer = (i: number, v: Answer | null) => {
    const a = { ...st.a }
    if (v) a[i] = v
    else delete a[i]
    save({ ...st, a })
  }
  const note = (i: number, text: string) => save({ ...st, n: { ...st.n, [i]: text } })
  return [st, answer, note]
}

function ReviewChecklist({ job, conv, objectType }: { job: Job; conv: Conversion; objectType?: string }) {
  const items = conv.checklist ?? []
  const [st, answer, note] = useReview(`review:${job.id}:${conv.target}:${conv.object_id}`)
  if (!items.length) return null
  const load = job.loads?.[conv.target]?.tables.find((t) => t.table_id === conv.object_id)
  const simPassed = !!load && load.created && load.checks_total > 0 && load.checks_passed === load.checks_total
  const auto = (i: number) => simPassed && items[i].text.startsWith(SIM_CHECK)
  const decisions = items.filter((it) => it.category === 'verify').length
  const answered = items.filter((_, i) => st.a[i] || auto(i)).length
  const fixes = items.filter((_, i) => st.a[i] === 'fix').length
  const effort = effortOf(objectType)
  return (
    <div className="checklist">
      <div className="checklist-head">
        <strong>
          What needs review: {decisions} decision{decisions === 1 ? '' : 's'} to answer, {items.length - decisions} check
          {items.length - decisions === 1 ? '' : 's'} to tick
        </strong>
        <span className="objbadges">
          {fixes > 0 && <span className="badge failed">{fixes} need{fixes === 1 ? 's' : ''} fix</span>}
          <span className={`badge ${answered === items.length ? 'passed' : 'manual_review'}`}>
            {answered} of {items.length} done
          </span>
        </span>
      </div>
      <div className={`effort-line effort-${effort.toLowerCase()}`}>{EFFORT_HINT[effort]}</div>
      {(['complete', 'verify', 'deploy', 'test'] as const).map((cat) => {
        const rows = items.map((it, i) => ({ it, i })).filter(({ it }) => it.category === cat)
        if (!rows.length) return null
        return (
          <div key={cat} className="checklist-group">
            <div className="checklist-cat">{cat === 'verify' ? 'Decide: accept or needs fix' : CATEGORY[cat]}</div>
            {rows.map(({ it, i }) =>
              cat === 'verify' ? (
                <div key={i} className={`decision ${st.a[i] ?? ''}`}>
                  <div className="decision-text">{it.text}</div>
                  <div className="decision-actions">
                    <button className={st.a[i] === 'accept' ? 'on accept' : ''} onClick={() => answer(i, st.a[i] === 'accept' ? null : 'accept')}>
                      Accept
                    </button>
                    <button className={st.a[i] === 'fix' ? 'on fix' : ''} onClick={() => answer(i, st.a[i] === 'fix' ? null : 'fix')}>
                      Needs fix
                    </button>
                    <input placeholder="Note (optional)" value={st.n[i] ?? ''} onChange={(e) => note(i, e.target.value)} />
                  </div>
                </div>
              ) : auto(i) ? (
                <label key={i} className="done auto">
                  <input type="checkbox" checked disabled /> {it.text} <span className="badge passed">Passed in simulated load</span>
                </label>
              ) : (
                <label key={i} className={st.a[i] ? 'done' : ''}>
                  <input type="checkbox" checked={!!st.a[i]} onChange={() => answer(i, st.a[i] ? null : 'done')} /> {it.text}
                </label>
              ),
            )}
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
  const typeOf = useMemo(() => Object.fromEntries(a.objects.map((o) => [o.id, o.object_type])), [a])
  const efforts = (['Light', 'Medium', 'Heavy'] as const)
    .map((e) => [e, convs.filter((c) => c.checklist?.length && effortOf(typeOf[c.object_id]) === e).length] as const)
    .filter(([, n]) => n)

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
          <Card
            title="Objects"
            extra={
              <span className="small muted" title="Review effort: Light = tables, Medium = views, Heavy = macros, procedures and BTEQ">
                {toReview} of {convs.length} need review{efforts.length ? ': ' : ''}
                {efforts.map(([e, n]) => `${e} ${n}`).join(' · ')}
              </span>
            }
          >
            <ul className="objlist">
              {convs.map((c) => (
                <li key={c.object_id} className={c.object_id === selected ? 'active' : ''} onClick={() => setSelected(c.object_id)}>
                  <span className="mono">{short(c.object_id)}</span>
                  <span className="objbadges">
                    {!!c.checklist?.length && (
                      <span className={`badge review effort-${effortOf(typeOf[c.object_id]).toLowerCase()}`} title={`${c.checklist.length} item(s) to review`}>
                        {effortOf(typeOf[c.object_id])} review · {c.checklist.length}
                      </span>
                    )}
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
              <ReviewChecklist job={job} conv={conv} objectType={typeOf[conv.object_id]} />
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
