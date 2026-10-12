import type { InputFile, Job } from '../api'
import { Card } from './common'
import { FORMAT_LABEL, kb } from './format'

function Side({ title, uploads, files }: { title: string; uploads: InputFile[]; files: InputFile[] | null }) {
  const groups = new Map<string, { n: number; size: number; gz: number }>()
  files?.forEach((f) => {
    const g = groups.get(f.detected_format) ?? { n: 0, size: 0, gz: 0 }
    g.n += 1
    g.size += f.size
    if (f.path.toLowerCase().endsWith('.gz')) g.gz += 1
    groups.set(f.detected_format, g)
  })
  const upSize = uploads.reduce((s, u) => s + u.size, 0)
  return (
    <div className="tile-side">
      <div className="tile-title">{title}</div>
      <div className="small">
        {uploads.length ? uploads.map((u) => `${u.path} (${kb(u.size)})`).join(', ') : <span className="muted">nothing uploaded</span>}
      </div>
      {uploads.length > 0 && (
        <div className="muted small">
          {uploads.length} upload(s), {kb(upSize)}
          {files && ` → ${files.length} file(s), ${kb(files.reduce((s, f) => s + f.size, 0))} unpacked`}
        </div>
      )}
      <div className="fmt-chips">
        {[...groups.entries()].map(([fmt, g]) => (
          <span key={fmt} className={`fmt-chip ${fmt}`}>
            <b>{g.n}</b> {FORMAT_LABEL[fmt] ?? fmt}
            {g.gz ? ` (${g.gz} gzip)` : ''} · {kb(g.size)}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function UploadSummary({ job }: { job: Job }) {
  const a = job.analysis
  const dataDone = job.progress?.stages.find((s) => s.key === 'data')?.status === 'done' || (!job.progress && !!a)
  return (
    <Card title="2 · What was uploaded" extra={<span className="muted small">file count, format and size of each dump</span>}>
      <div className="tile">
        <Side title="Configuration dump" uploads={job.uploads.filter((u) => u.kind === 'config')} files={a ? a.config_files : null} />
        <Side title="Data dump" uploads={job.uploads.filter((u) => u.kind === 'data')} files={a && dataDone ? a.data_files : null} />
      </div>
    </Card>
  )
}
