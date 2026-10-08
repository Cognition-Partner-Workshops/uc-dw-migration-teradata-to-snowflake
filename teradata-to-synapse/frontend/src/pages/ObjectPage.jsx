import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { navigate } from '../nav.js'
import { diffStats, splitDiff } from '../diff.js'
import { StatusBadge, TYPE_LABELS, flattenInventory } from '../format.jsx'

function SplitView({ source, generated, highlight }) {
  const rows = useMemo(() => splitDiff(source, generated), [source, generated])
  const stats = diffStats(rows)
  return (
    <>
      <div className="diff-stats muted">
        {stats.change} changed · {stats.del} removed · {stats.add} added lines
      </div>
      <div className={`split ${highlight ? 'highlight' : ''}`}>
        <div className="split-head">Teradata source</div>
        <div className="split-head">Azure Synapse T-SQL</div>
        {rows.map((r, idx) => (
          <div key={idx} className={`split-row row-${r.type}`}>
            <div className={`cell left ${r.left === null ? 'empty' : ''}`}>
              <span className="ln">{r.leftNo ?? ''}</span>
              <code>{r.left ?? ''}</code>
            </div>
            <div className={`cell right ${r.right === null ? 'empty' : ''}`}>
              <span className="ln">{r.rightNo ?? ''}</span>
              <code>{r.right ?? ''}</code>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

export default function ObjectPage({ jobId, objectId }) {
  const [job, setJob] = useState(null)
  const [obj, setObj] = useState(null)
  const [error, setError] = useState(null)
  const [highlight, setHighlight] = useState(true)

  useEffect(() => {
    let live = true
    setObj(null)
    Promise.all([api.getJob(jobId), api.getObject(jobId, objectId)])
      .then(([j, o]) => {
        if (!live) return
        setJob(j)
        setObj(o)
      })
      .catch((e) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [jobId, objectId])

  const all = useMemo(() => flattenInventory(job), [job])
  const idx = all.findIndex((o) => o.id === objectId)
  const prev = idx > 0 ? all[idx - 1] : null
  const next = idx >= 0 && idx < all.length - 1 ? all[idx + 1] : null
  const converted = job && job.status !== 'scanned'

  if (error) return <div className="error">{error}</div>
  if (!obj) return <div className="muted">Loading…</div>

  return (
    <section>
      <div className="page-head">
        <div>
          <a href={`#/jobs/${jobId}`} className="back">
            ← Inventory
          </a>
          <h1 className="mono">{obj.object_name}</h1>
          <p className="muted">
            {TYPE_LABELS[obj.object_type]} · <span className="mono">{obj.rel_path}</span>
            {obj.output_path && (
              <>
                {' '}
                → <span className="mono">{obj.output_path}</span>
              </>
            )}{' '}
            · <StatusBadge status={obj.status} />
          </p>
        </div>
        <div className="actions">
          <button disabled={!prev} onClick={() => navigate(`/jobs/${jobId}/objects/${prev.id}`)}>
            ‹ Prev
          </button>
          <button disabled={!next} onClick={() => navigate(`/jobs/${jobId}/objects/${next.id}`)}>
            Next ›
          </button>
          {converted ? (
            <a className="button primary" href={api.downloadUrl(jobId)}>
              Download Zip
            </a>
          ) : (
            <button className="primary" disabled title="Convert the job first">
              Download Zip
            </button>
          )}
        </div>
      </div>

      {obj.manual_reason && (
        <div className="callout manual">
          <strong>{obj.status === 'failed' ? 'Conversion failed' : 'Manual review required'}:</strong>{' '}
          {obj.manual_reason}
        </div>
      )}

      {(obj.rules.length > 0 || obj.warnings.length > 0) && (
        <div className="notes">
          {obj.rules.length > 0 && (
            <details open={obj.object_type === 'table'}>
              <summary>Rules applied ({obj.rules.length})</summary>
              <ul>
                {obj.rules.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </details>
          )}
          {obj.warnings.length > 0 && (
            <details open>
              <summary>Review warnings ({obj.warnings.length})</summary>
              <ul className="warnings">
                {obj.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {obj.generated_sql == null ? (
        <div className="callout">
          Not converted yet. <a href={`#/jobs/${jobId}`}>Go back and click “Convert All”.</a>
          <pre className="source-only">{obj.source_sql}</pre>
        </div>
      ) : (
        <>
          <label className="toggle">
            <input type="checkbox" checked={highlight} onChange={(e) => setHighlight(e.target.checked)} /> Highlight
            changes
          </label>
          <SplitView source={obj.source_sql} generated={obj.generated_sql} highlight={highlight} />
        </>
      )}
    </section>
  )
}
