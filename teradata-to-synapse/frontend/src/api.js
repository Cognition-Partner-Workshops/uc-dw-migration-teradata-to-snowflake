const BASE = import.meta.env.VITE_API_BASE || '/api'

async function request(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `${method} ${path} failed (${res.status})`)
  return data
}

export const api = {
  createJob: (repoUrl) => request('POST', '/jobs', { repo_url: repoUrl }),
  getJob: (jobId) => request('GET', `/jobs/${jobId}`),
  convertAll: (jobId) => request('POST', `/jobs/${jobId}/convert`),
  getObject: (jobId, objectId) => request('GET', `/jobs/${jobId}/objects/${objectId}`),
  downloadUrl: (jobId) => `${BASE}/jobs/${jobId}/download`,
  reportUrl: (jobId) => `${BASE}/output/${jobId}/SQL_TRANSLATION_NOTES.md`,
}
