import { useEffect, useState } from 'react'
import { api } from './api'
import type { Formats, Job, TargetId } from './api'
import UploadStep from './steps/UploadStep'
import AnalyseStep from './steps/AnalyseStep'
import OutputsStep from './steps/OutputsStep'
import LoadStep from './steps/LoadStep'
import HistoryPanel from './steps/HistoryPanel'

const STEPS = ['Upload dumps', 'Analyse & validate', 'Migration outputs', 'Load & validate'] as const
const POLL_MS = 400

export default function App() {
  const [formats, setFormats] = useState<Formats | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  useEffect(() => {
    api.formats().then(setFormats).catch((e: Error) => setError(e.message))
  }, [])

  const running = job?.status === 'running'
  useEffect(() => {
    if (!job || job.status !== 'running') return
    const t = setTimeout(() => {
      api
        .job(job.id)
        .then((j) => {
          setJob(j)
          if (j.error) setError(j.error)
        })
        .catch((e: Error) => setError(e.message))
    }, POLL_MS)
    return () => clearTimeout(t)
  }, [job])

  const run = async (label: string, fn: () => Promise<Job>, next?: number) => {
    setBusy(label)
    setError(null)
    try {
      const j = await fn()
      setJob(j)
      if (j.error) setError(j.error)
      else if (next !== undefined) setStep(next)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const open = (id: string) => {
    setShowHistory(false)
    run('Opening job', () => api.job(id)).then(() => setStep(1))
  }

  const target: TargetId = job?.options.targets[0] ?? 'bigquery'
  const ready = job?.status === 'analysed' || job?.status === 'loaded'
  const enabled = (i: number) => i === 0 || (i === 1 ? !!job : ready)

  return (
    <div className="app">
      <header>
        <div>
          <h1>Teradata → Cloud Migrator</h1>
          <p className="sub">Proof of concept · configuration + data dumps → BigQuery · Redshift · Synapse</p>
        </div>
        <div className="header-actions">
          {job && (
            <div className="job-chip" title={job.id}>
              {job.name} · {formats?.targets[target]?.split(' (')[0] ?? target}{' '}
              <span className={`badge ${job.status}`}>{running ? `running ${job.progress?.percent ?? 0}%` : job.status}</span>
            </div>
          )}
          <button className={showHistory ? 'active-toggle' : ''} onClick={() => setShowHistory(!showHistory)}>
            Job history (last 10)
          </button>
        </div>
      </header>
      <nav className="stepper">
        {STEPS.map((s, i) => (
          <button key={s} className={i === step ? 'active' : ''} disabled={!enabled(i)} onClick={() => setStep(i)}>
            <span className="num">{i + 1}</span> {s}
          </button>
        ))}
      </nav>
      {showHistory && (
        <HistoryPanel formats={formats} currentId={job?.id ?? null} refreshKey={`${job?.id}:${job?.status}`} onOpen={open} onClose={() => setShowHistory(false)} />
      )}
      {error && <div className="alert error">{error}</div>}
      {busy && <div className="alert info">{busy}…</div>}
      <main>
        {step === 0 && formats && (
          <UploadStep
            formats={formats}
            busy={!!busy || running}
            onSubmit={(c, d, o, n) => run('Uploading dumps', () => api.createJob(c, d, o, n), 1)}
            onExample={(t, pace) => run('Starting the BANKING_DW example', () => api.runExample(t, pace), 1)}
          />
        )}
        {step === 1 && job && (
          <AnalyseStep
            job={job}
            formats={formats}
            onOverride={(file, table) => run('Re-validating data mapping', () => api.setMappings(job.id, { [file]: table }))}
            onNext={() => setStep(2)}
          />
        )}
        {step === 2 && ready && job?.analysis && <OutputsStep job={job} target={target} formats={formats} onNext={() => setStep(3)} />}
        {step === 3 && ready && job?.analysis && (
          <LoadStep job={job} target={target} formats={formats} busy={!!busy} onLoad={() => run('Creating tables and loading data', () => api.load(job.id, [target]))} />
        )}
      </main>
      <footer>Simulated loads run in a local DuckDB warehouse that mirrors the chosen target&apos;s types. Real-cloud load scripts are generated but not executed.</footer>
    </div>
  )
}
