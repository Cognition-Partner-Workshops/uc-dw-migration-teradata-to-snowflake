import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { navigate } from '../nav.js'
import { StatusBadge, TYPE_LABELS, flattenInventory } from '../format.jsx'

export default function InventoryPage({ jobId }) {
  const [job, setJob] = useState(null)
  const [filter, setFilter] = useState('all')
  const [converting, setConverting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    api
      .getJob(jobId)
      .then((j) => live && setJob(j))
      .catch((e) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [jobId])

  const objects = useMemo(() => flattenInventory(job), [job])
  const visible = filter === 'all' ? objects : objects.filter((o) => o.object_type === filter)
  const converted = job && (job.status === 'converted' || job.status === 'partially_converted')

  async function convertAll() {
    setConverting(true)
    setError(null)
    try {
      setJob(await api.convertAll(jobId))
    } catch (e) {
      setError(e.message)
    } finally {
      setConverting(false)
    }
  }

  if (error && !job) return <div className="error">{error}</div>
  if (!job) return <div className="muted">Loading job…</div>

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Inventory</h1>
          <p className="muted">
            {job.repo_url} · job <code>{job.job_id}</code> · {job.total_objects} objects
          </p>
        </div>
        <div className="actions">
          {converted && (
            <>
              <a className="button" href={api.reportUrl(jobId)} target="_blank" rel="noreferrer">
                Translation notes
              </a>
              <a className="button" href={api.downloadUrl(jobId)}>
                Download Zip
              </a>
            </>
          )}
          <button className="primary" onClick={convertAll} disabled={converting || job.total_objects === 0}>
            {converting ? 'Converting…' : converted ? 'Re-convert All' : 'Convert All'}
          </button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}

      <div className="summary">
        {Object.entries(job.counts_by_status).map(([status, n]) => (
          <div key={status} className="summary-item">
            <StatusBadge status={status} /> <strong>{n}</strong>
          </div>
        ))}
      </div>

      <div className="tabs">
        <button className={filter === 'all' ? 'tab active' : 'tab'} onClick={() => setFilter('all')}>
          All ({job.total_objects})
        </button>
        {Object.entries(job.counts_by_type).map(([type, n]) => (
          <button
            key={type}
            className={filter === type ? 'tab active' : 'tab'}
            onClick={() => setFilter(type)}
            disabled={n === 0}
          >
            {TYPE_LABELS[type]} ({n})
          </button>
        ))}
      </div>

      <table className="inventory">
        <thead>
          <tr>
            <th>Object</th>
            <th>Type</th>
            <th>Source file</th>
            <th>Convert status</th>
            <th>Warnings</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {visible.map((o) => (
            <tr key={o.id} className="clickable" onClick={() => navigate(`/jobs/${jobId}/objects/${o.id}`)}>
              <td className="mono">{o.object_name}</td>
              <td>{TYPE_LABELS[o.object_type]}</td>
              <td className="mono muted">{o.rel_path}</td>
              <td>
                <StatusBadge status={o.status} />
              </td>
              <td>{o.status === 'pending' ? '—' : o.warning_count}</td>
              <td>
                <a href={`#/jobs/${jobId}/objects/${o.id}`} onClick={(e) => e.stopPropagation()}>
                  View →
                </a>
              </td>
            </tr>
          ))}
          {visible.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                No .sql/.bteq files found under ddl/ or dml/.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
