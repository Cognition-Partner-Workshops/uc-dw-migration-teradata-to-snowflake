export type TargetId = 'bigquery' | 'redshift' | 'synapse'
export type Status = 'converted' | 'converted_with_warnings' | 'manual_review' | 'unsupported'

export interface Formats {
  config: { formats: Record<string, string>; extensions: string[] }
  data: { formats: Record<string, string>; extensions: string[]; delimiters: Record<string, string> }
  targets: Record<TargetId, string>
}
export interface InputFile { path: string; size: number; kind: string; detected_format: string; note: string | null }
export interface Column { name: string; td_type: string; nullable: boolean; default: string | null; identity: object | null }
export interface TableMeta {
  database: string; name: string; kind: string; columns: Column[]; primary_index: string[]; primary_index_unique: boolean
  partition_expression: string | null; partition_columns: string[]; unique_keys: string[][]; comment: string | null
}
export interface SourceObject {
  id: string; object_type: string; database: string; name: string; source_file: string; source_format: string; sql: string
  table: TableMeta | null; dependencies: string[]; features: string[]; parse_error: string | null
}
export interface Conversion { object_id: string; target: TargetId; status: Status; sql: string; rules: string[]; warnings: string[]; reason: string | null }
export interface ColumnMapping { column: string; td_type: string; target_type: string; nullable: boolean; lossy: boolean; note: string | null }
export interface DataFile {
  path: string; format: string; delimiter: string | null; has_header: boolean | null; compressed: boolean; row_count: number
  column_count: number; columns: string[]; table_id: string | null; match_method: string; match_confidence: number; issues: string[]
}
export interface ColumnCheck { column: string; source: string; parse_errors: number; null_violations: number; length_violations: number; samples: string[] }
export interface Readiness {
  table_id: string; files: string[]; status: 'ready' | 'ready_with_warnings' | 'blocked' | 'no_data'; total_rows: number
  rejected_rows: number; duplicate_rows: number; unmapped_file_columns: string[]; columns: ColumnCheck[]; issues: string[]
}
export interface Analysis {
  config_files: InputFile[]; data_files: InputFile[]; objects: SourceObject[]; create_order: string[]; conversions: Conversion[]
  type_mappings: Record<string, Record<string, ColumnMapping[]>>; data: DataFile[]; readiness: Readiness[]; manifest: string | null; messages: string[]
}
export interface TableLoad {
  table_id: string; target_table: string; created: boolean; files: string[]; source_rows: number; rejected_rows: number; loaded_rows: number
  checks_passed: number; checks_total: number; failed_checks: string[]; status: string; error: string | null
}
export interface ViewLoad { object_id: string; target_view: string; created: boolean; row_count: number | null; error: string | null }
export interface LoadResult { target: TargetId; tables: TableLoad[]; views: ViewLoad[]; status: string; finished_at: string }
export interface DataOptions { data_format: string; delimiter: string; header: 'auto' | 'yes' | 'no'; encoding: string; empty_as_null: boolean }
export interface JobOptions { targets: TargetId[]; config_format: string; data: DataOptions }
export interface Job {
  id: string; name: string; created_at: string; status: string; options: JobOptions; analysis: Analysis | null
  loads: Partial<Record<TargetId, LoadResult>>; error: string | null
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  }
  return r.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  formats: () => call<Formats>('/api/formats'),
  createJob: (config: File[], data: File[], options: Partial<JobOptions>, name: string) => {
    const fd = new FormData()
    config.forEach((f) => fd.append('config_files', f, f.name))
    data.forEach((f) => fd.append('data_files', f, f.name))
    fd.append('options', JSON.stringify(options))
    fd.append('name', name)
    return call<Job>('/api/jobs', { method: 'POST', body: fd })
  },
  runExample: () => call<Job>('/api/examples/banking_dw/run', { method: 'POST' }),
  setMappings: (id: string, overrides: Record<string, string>) => call<Job>(`/api/jobs/${id}/mappings`, json({ overrides })),
  load: (id: string, targets: TargetId[]) => call<Job>(`/api/jobs/${id}/load`, json({ targets })),
  outputs: (id: string) => call<Record<string, string>>(`/api/jobs/${id}/outputs`),
  bundleUrl: (id: string) => `/api/jobs/${id}/bundle.zip`,
  exampleUrl: (file: string) => `/api/examples/banking_dw/${file}`,
}
