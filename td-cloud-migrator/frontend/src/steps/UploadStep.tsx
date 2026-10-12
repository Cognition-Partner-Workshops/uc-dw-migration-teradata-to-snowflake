import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { api } from '../api'
import type { DataOptions, Formats, JobOptions, TargetId } from '../api'
import { Card } from './common'
import { kb } from './format'

interface Props {
  formats: Formats
  busy: boolean
  onSubmit: (config: File[], data: File[], options: Partial<JobOptions>, name: string) => void
  onExample: (target: TargetId, pace: number) => void
}

function DropZone({ files, setFiles, accept, label }: { files: File[]; setFiles: (f: File[]) => void; accept: string; label: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const add = (list: FileList | null) => {
    if (!list) return
    const names = new Set(files.map((f) => f.name))
    setFiles([...files, ...Array.from(list).filter((f) => !names.has(f.name))])
  }
  const drop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    add(e.dataTransfer.files)
  }
  return (
    <div>
      <div
        className={`dropzone ${over ? 'over' : ''}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
      >
        <strong>Drop files here or click to browse</strong>
        <span>{label}</span>
        <input ref={input} type="file" multiple accept={accept} hidden onChange={(e) => add(e.target.files)} />
      </div>
      {files.length > 0 && (
        <ul className="filelist">
          {files.map((f) => (
            <li key={f.name}>
              <span>{f.name}</span>
              <span className="muted">{kb(f.size)}</span>
              <button className="link" onClick={() => setFiles(files.filter((x) => x !== f))}>
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function FormatList({ formats }: { formats: Record<string, string> }) {
  return (
    <ul className="formats">
      {Object.entries(formats)
        .filter(([k]) => k !== 'auto')
        .map(([k, v]) => (
          <li key={k}>{v}</li>
        ))}
    </ul>
  )
}

export default function UploadStep({ formats, busy, onSubmit, onExample }: Props) {
  const [config, setConfig] = useState<File[]>([])
  const [data, setData] = useState<File[]>([])
  const [configFormat, setConfigFormat] = useState('auto')
  const [dataOpts, setDataOpts] = useState<DataOptions>({ data_format: 'auto', delimiter: 'auto', header: 'auto', encoding: 'utf-8', empty_as_null: true })
  const [target, setTarget] = useState<TargetId>('bigquery')
  const [name, setName] = useState('')
  const [pace, setPace] = useState(true)

  return (
    <>
      <div className="grid3">
        <Card title="1 · Configuration / metadata dump">
          <p className="muted">Describes how the Teradata system is structured: databases, tables, column types, primary indexes, partitioning, constraints, views, macros, stored procedures and scripts.</p>
          <label className="field">
            Dump format
            <select value={configFormat} onChange={(e) => setConfigFormat(e.target.value)}>
              {Object.entries(formats.config.formats).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <div className="accepted">
            <strong>Accepted formats</strong>
            <FormatList formats={formats.config.formats} />
          </div>
          <DropZone files={config} setFiles={setConfig} accept={formats.config.extensions.join(',')} label={formats.config.extensions.join('  ')} />
        </Card>
        <Card title="2 · Data dump">
          <p className="muted">The table records exported from Teradata, one or more files per table, optionally with a manifest that maps tables to files.</p>
          <div className="row3">
            <label className="field">
              Data format
              <select value={dataOpts.data_format} onChange={(e) => setDataOpts({ ...dataOpts, data_format: e.target.value })}>
                {Object.entries(formats.data.formats).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Delimiter
              <select value={dataOpts.delimiter} onChange={(e) => setDataOpts({ ...dataOpts, delimiter: e.target.value })}>
                {Object.entries(formats.data.delimiters).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Header row
              <select value={dataOpts.header} onChange={(e) => setDataOpts({ ...dataOpts, header: e.target.value as DataOptions['header'] })}>
                <option value="auto">Auto-detect</option>
                <option value="yes">First row is a header</option>
                <option value="no">No header</option>
              </select>
            </label>
          </div>
          <div className="accepted">
            <strong>Accepted formats</strong>
            <FormatList formats={formats.data.formats} />
          </div>
          <DropZone files={data} setFiles={setData} accept={formats.data.extensions.join(',')} label={formats.data.extensions.join('  ')} />
        </Card>
        <Card title="3 · Target and run">
          <p className="muted">Choose the one cloud platform to migrate to. All converted SQL, reports, load scripts and the simulated load are produced for this target only.</p>
          <div className="target-pick">
            {(Object.entries(formats.targets) as [TargetId, string][]).map(([k, v]) => (
              <label key={k} className={`radio ${target === k ? 'on' : ''}`}>
                <input type="radio" name="target" checked={target === k} onChange={() => setTarget(k)} /> {v}
              </label>
            ))}
          </div>
          <label className="field">
            Job name (optional)
            <input className="name" placeholder="e.g. Client A – wave 1" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button
            className="primary wide"
            disabled={busy || config.length === 0}
            onClick={() => onSubmit(config, data, { targets: [target], config_format: configFormat, data: dataOpts }, name)}
          >
            Analyse &amp; convert
          </button>
          {config.length === 0 && <p className="muted small">Add at least one configuration file to start.</p>}
          <div className="example">
            <strong>Worked example: BANKING_DW</strong>
            <span className="muted small">
              7 tables, 3 views, 3 macros, 3 procedures and 2 BTEQ scripts, plus pipe-delimited, Parquet and split/gzipped fact files with a YAML manifest.
            </span>
            <div className="example-actions">
              <a href={api.exampleUrl('config_dump.zip')}>config_dump.zip</a>
              <a href={api.exampleUrl('config_dump_dbc.zip')}>config_dump_dbc.zip (DBC)</a>
              <a href={api.exampleUrl('data_dump.zip')}>data_dump.zip</a>
            </div>
            <label className="check small" title="Each stage takes at least about 1.5 seconds so the audience can follow the progress bar. Real uploads always run at full speed.">
              <input type="checkbox" checked={pace} onChange={(e) => setPace(e.target.checked)} /> Presentation pace (show each stage, ~8s)
            </label>
            <button className="wide" disabled={busy} onClick={() => onExample(target, pace ? 1.5 : 0)}>
              Run example on {formats.targets[target].split(' (')[0]}
            </button>
          </div>
        </Card>
      </div>
    </>
  )
}
