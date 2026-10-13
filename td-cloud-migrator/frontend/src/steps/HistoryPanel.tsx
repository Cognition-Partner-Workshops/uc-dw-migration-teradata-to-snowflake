import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Formats, History } from '../api'
import { Badge, Card } from './common'
import { secs, when } from './format'

interface Props {
  formats: Formats | null
  currentId: string | null
  refreshKey: string
  onOpen: (id: string) => void
  onClose: () => void
}

export default function HistoryPanel({ formats, currentId, refreshKey, onOpen, onClose }: Props) {
  const [h, setH] = useState<History | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.history().then(setH).catch((e: Error) => setErr(e.message))
  }, [refreshKey])
  return (
    <Card
      title={`Job history · last ${h?.limit ?? 10} jobs`}
      extra={
        <span className="muted small">
          {h && `Showing ${h.jobs.length} of ${h.total} job(s), newest first; history goes back ${h.limit} jobs. `}
          <button className="link plain" onClick={onClose}>close</button>
        </span>
      }
    >
      {err && <div className="alert error">{err}</div>}
      {h && h.jobs.length === 0 && <p className="muted">No jobs yet.</p>}
      {h && h.jobs.length > 0 && (
        <table>
          <thead>
            <tr><th>#</th><th>Started</th><th>Job</th><th>Target</th><th>Uploads</th><th>Objects</th><th>Data files</th><th>Rows</th><th>Need review</th><th>Loaded rows</th><th>Duration</th><th>Status</th><th /></tr>
          </thead>
          <tbody>
            {h.jobs.map((j, i) => (
              <tr key={j.id} className={j.id === currentId ? 'current' : ''}>
                <td>{i + 1}</td>
                <td className="small">{when(j.created_at)}</td>
                <td>{j.name}</td>
                <td>{j.targets.map((t) => formats?.targets[t]?.split(' (')[0] ?? t).join(', ')}</td>
                <td className="small mono">{j.uploads.join(', ') || '—'}</td>
                <td>{j.objects}</td>
                <td>{j.data_files}</td>
                <td>{j.rows.toLocaleString()}</td>
                <td>{j.manual_review}</td>
                <td>{j.loaded_rows ? j.loaded_rows.toLocaleString() : '—'}</td>
                <td>{j.duration_seconds === null ? '—' : secs(j.duration_seconds)}</td>
                <td><Badge status={j.status} /></td>
                <td>
                  {j.id === currentId ? <span className="muted small">open</span> : <button onClick={() => onOpen(j.id)}>Open</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
