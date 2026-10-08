import { useState } from 'react'
import { api } from '../api.js'
import { navigate } from '../nav.js'

export const DEMO_REPO = 'https://github.com/Cognition-Partner-Workshops/uc-dw-migration-teradata-to-snowflake'

export default function ScanPage() {
  const [repoUrl, setRepoUrl] = useState(DEMO_REPO)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function onScan(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const job = await api.createJob(repoUrl)
      navigate(`/jobs/${job.job_id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card scan-card">
      <h1>Scan a Teradata repository</h1>
      <p className="muted">
        The repository is cloned and every <code>.sql</code> / <code>.bteq</code> file under <code>ddl/</code> and{' '}
        <code>dml/</code> is classified as a table, view, macro, stored procedure or BTEQ script.
      </p>
      <form onSubmit={onScan} className="scan-form">
        <label htmlFor="repo-url">Source repo URL</label>
        <div className="row">
          <input
            id="repo-url"
            type="url"
            required
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/org/teradata-repo"
            disabled={busy}
          />
          <button type="submit" className="primary" disabled={busy || !repoUrl.trim()}>
            {busy ? 'Scanning…' : 'Scan'}
          </button>
        </div>
        {repoUrl !== DEMO_REPO && (
          <button type="button" className="link" onClick={() => setRepoUrl(DEMO_REPO)}>
            Use the BANKING_DW demo repository
          </button>
        )}
      </form>
      {error && <div className="error">{error}</div>}
    </section>
  )
}
