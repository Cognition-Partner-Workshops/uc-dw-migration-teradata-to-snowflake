import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import type { Formats, Job, TargetId } from './api'
import UploadStep from './steps/UploadStep'
import AnalyseStep from './steps/AnalyseStep'
import OutputsStep from './steps/OutputsStep'
import LoadStep from './steps/LoadStep'

const STEPS = ['Upload dumps', 'Analyse & validate', 'Migration outputs', 'Load & validate'] as const

export default function App() {
  const [formats, setFormats] = useState<Formats | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.formats().then(setFormats).catch((e: Error) => setError(e.message))
  }, [])

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

  const targets = useMemo<TargetId[]>(() => job?.options.targets ?? ['bigquery', 'redshift', 'synapse'], [job])

  return (
    <div className="app">
      <header>
        <div>
          <h1>Teradata → Cloud Migrator</h1>
          <p className="sub">Proof of concept · configuration + data dumps → BigQuery · Redshift · Synapse</p>
        </div>
        {job && (
          <div className="job-chip" title={job.id}>
            {job.name} <span className={`badge ${job.status}`}>{job.status}</span>
          </div>
        )}
      </header>
      <nav className="stepper">
        {STEPS.map((s, i) => (
          <button key={s} className={i === step ? 'active' : ''} disabled={i > 0 && !job?.analysis} onClick={() => setStep(i)}>
            <span className="num">{i + 1}</span> {s}
          </button>
        ))}
      </nav>
      {error && <div className="alert error">{error}</div>}
      {busy && <div className="alert info">{busy}…</div>}
      <main>
        {step === 0 && formats && (
          <UploadStep
            formats={formats}
            busy={!!busy}
            onSubmit={(c, d, o, n) => run('Uploading, analysing and converting', () => api.createJob(c, d, o, n), 1)}
            onExample={() => run('Running the BANKING_DW example', api.runExample, 1)}
          />
        )}
        {step === 1 && job?.analysis && (
          <AnalyseStep
            job={job}
            formats={formats}
            onOverride={(file, table) => run('Re-validating data mapping', () => api.setMappings(job.id, { [file]: table }))}
            onNext={() => setStep(2)}
          />
        )}
        {step === 2 && job?.analysis && <OutputsStep job={job} targets={targets} formats={formats} onNext={() => setStep(3)} />}
        {step === 3 && job?.analysis && (
          <LoadStep job={job} targets={targets} formats={formats} busy={!!busy} onLoad={(t) => run('Creating tables and loading data', () => api.load(job.id, t))} />
        )}
      </main>
      <footer>Simulated loads run in local DuckDB warehouses that mirror each target's types. Real-cloud load scripts are generated but not executed.</footer>
    </div>
  )
}
