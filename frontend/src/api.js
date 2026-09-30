/** 后端 API 封装。统一错误信息提取。 */

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new Error(formatError(data));
  }
  return data;
}

export function formatError(data) {
  if (!data) return '请求失败';
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d) => {
        const loc = Array.isArray(d.loc)
          ? d.loc.filter((x) => x !== 'body').join(' › ')
          : '';
        return `${loc ? loc + '：' : ''}${d.msg}`;
      })
      .join('；');
  }
  return '请求失败';
}

export const api = {
  listExperiments: () => request('/api/experiments'),
  getExperiment: (id) => request(`/api/experiments/${id}`),
  createExperiment: (payload) =>
    request('/api/experiments', { method: 'POST', body: JSON.stringify(payload) }),
  deleteExperiment: (id) =>
    request(`/api/experiments/${id}`, { method: 'DELETE' }),
  addSamples: (id, samples) =>
    request(`/api/experiments/${id}/samples`, {
      method: 'POST',
      body: JSON.stringify({ samples }),
    }),
  setLock: (id, position, locked) =>
    request(
      `/api/experiments/${id}/pools/${position}/lock?locked=${locked}`,
      { method: 'POST' }
    ),
  remeasure: (id, updates) =>
    request(`/api/experiments/${id}/remeasure`, {
      method: 'POST',
      body: JSON.stringify({ updates }),
    }),
  getVersion: (id, versionNo) =>
    request(`/api/experiments/${id}/versions/${versionNo}`),
};
