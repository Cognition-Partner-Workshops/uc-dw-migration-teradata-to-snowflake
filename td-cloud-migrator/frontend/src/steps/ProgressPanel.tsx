import { useEffect, useState } from 'react'
import type { Job } from '../api'
import { Card } from './common'
import { clock, secs } from './format'

export default function ProgressPanel({ job }: { job: Job }) {
  const p = job.progress
  const running = job.status === 'running'
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [running])
  if (!p) return null
  const start = Date.parse(p.started_at)
  const end = p.finished_at ? Date.parse(p.finished_at) : now
  const elapsed = Math.max(0, (end - start) / 1000)
  const eta = running && p.percent >= 3 ? (elapsed * (100 - p.percent)) / p.percent : null
  const current = p.stages.find((s) => s.key === p.current)
  const failed = job.status === 'failed'
  const title = running ? 'Job running' : failed ? 'Job failed' : 'Job completed'
  return (
    <Card title={`1 · ${title}`} extra={<span className="muted small">Started {clock(p.started_at)} · job {job.id}</span>}>
      <div className="progress-head">
        <div className="pct">{p.percent}%</div>
        <div className="progress-meta">
          <div>
            <strong>{running ? (current?.label ?? 'Starting') : failed ? 'Stopped' : 'All stages completed'}</strong>
            {running && current?.detail && <span className="muted"> · {current.detail}</span>}
          </div>
          <div className="muted small">
            Elapsed {secs(elapsed)}
            {running && <> · ETA {eta === null ? 'estimating…' : secs(eta)}</>}
            {!running && !failed && <> · finished {clock(p.finished_at)}</>}
          </div>
        </div>
      </div>
      <div className={`bar ${failed ? 'failed' : ''}`}>
        <div style={{ width: `${p.percent}%` }} />
      </div>
      <ol className="timeline">
        {p.stages.map((s) => (
          <li key={s.key} className={s.status}>
            <span className="dot" />
            <span className="t-label">{s.label}</span>
            <span className="t-detail small muted">{s.detail ?? (s.status === 'pending' ? 'waiting' : '')}</span>
            <span className="t-time small mono">
              {s.started_at ? clock(s.started_at) : '—'}
              {s.started_at && s.finished_at && ` · ${secs((Date.parse(s.finished_at) - Date.parse(s.started_at)) / 1000)}`}
              {s.status === 'running' && ` · ${s.percent}%`}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  )
}
