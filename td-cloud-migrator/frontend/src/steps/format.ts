export const STATUS_LABEL: Record<string, string> = {
  converted: 'Converted',
  converted_with_warnings: 'Converted with warnings',
  manual_review: 'Manual review',
  unsupported: 'Unsupported',
  ready: 'Ready',
  ready_with_warnings: 'Ready with warnings',
  blocked: 'Blocked',
  no_data: 'No data',
  passed: 'Passed',
  passed_with_rejects: 'Passed (rows rejected)',
  passed_with_warnings: 'Passed with warnings',
  failed: 'Failed',
  structure_only: 'Structure only',
  running: 'Running',
  analysed: 'Analysed',
  loaded: 'Loaded',
  uploaded: 'Uploaded',
}

export const short = (id: string | null) => (id ? id.split(':').slice(1).join(':') : '—')
export const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

export const FORMAT_LABEL: Record<string, string> = {
  ddl_sql: 'SQL / DDL',
  bteq: 'BTEQ',
  dbc_csv: 'DBC CSV',
  dbc_json: 'DBC JSON',
  delimited: 'CSV / delimited',
  parquet: 'Parquet',
  manifest: 'Manifest',
  unknown: 'Unrecognised',
}
export const secs = (s: number) => (s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`)
export const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString() : '—')
export const when = (iso: string) => new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
