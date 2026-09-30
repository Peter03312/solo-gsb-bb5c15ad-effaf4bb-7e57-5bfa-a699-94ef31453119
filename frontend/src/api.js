// Thin client for the FastAPI backend. Same-origin in production (static served
// by FastAPI); Vite proxies /api during development.

async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return null
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    let message = `请求失败 (${res.status})`
    if (data) {
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) {
        message = data.detail
          .map((e) => {
            const field = Array.isArray(e.loc) ? e.loc.slice(1).join('.') : ''
            return field ? `${field}: ${e.msg}` : e.msg
          })
          .join('；')
      }
    }
    const err = new Error(message)
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  listBatches: () => request('GET', '/api/batches'),
  createBatch: (payload) => request('POST', '/api/batches', payload),
  getBatch: (id) => request('GET', `/api/batches/${id}`),
  deleteBatch: (id) => request('DELETE', `/api/batches/${id}`),
  addSamples: (id, samples) =>
    request('POST', `/api/batches/${id}/samples`, { samples }),
  deleteSample: (batchId, sampleId) =>
    request('DELETE', `/api/batches/${batchId}/samples/${sampleId}`),
  plan: (id) => request('POST', `/api/batches/${id}/plan`),
  lock: (batchId, poolNo) =>
    request('POST', `/api/batches/${batchId}/pools/${poolNo}/lock`),
  unlock: (batchId, poolNo) =>
    request('POST', `/api/batches/${batchId}/pools/${poolNo}/unlock`),
  remeasure: (batchId, sampleId, concentration) =>
    request('POST', `/api/batches/${batchId}/samples/${sampleId}/remeasure`, {
      concentration,
    }),
}
