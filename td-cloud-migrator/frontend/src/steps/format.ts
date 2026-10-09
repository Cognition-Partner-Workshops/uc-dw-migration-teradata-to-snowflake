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
}

export const short = (id: string | null) => (id ? id.split(':').slice(1).join(':') : '—')
export const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)
