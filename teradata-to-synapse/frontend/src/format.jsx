export const TYPE_LABELS = {
  table: 'Table',
  view: 'View',
  macro: 'Macro',
  stored_procedure: 'Stored procedure',
  script: 'BTEQ script',
}

export const STATUS_LABELS = {
  pending: 'Pending',
  converted: 'Converted',
  converted_with_warnings: 'Converted (review warnings)',
  manual_review: 'Manual review',
  failed: 'Failed',
}

export function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status] || status}</span>
}

export function flattenInventory(job) {
  if (!job) return []
  return Object.values(job.inventory).flat().sort((a, b) => a.rel_path.localeCompare(b.rel_path))
}
