const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  stats: () => request('/stats'),
  channels: () => request('/channels'),
  emails: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null),
    ).toString()
    return request(`/emails?${q}`)
  },
  emailDetail: (id) => request(`/emails/${id}`),
  attachments: (params = {}) => {
    const q = new URLSearchParams(params).toString()
    return request(`/attachments?${q}`)
  },
  attachmentDetail: (id) => request(`/attachments/${id}`),
  anomalies: () => request('/anomalies'),
  conflicts: () => request('/conflicts'),
  upload: async (formData) => {
    const res = await fetch(`${BASE}/uploads`, { method: 'POST', body: formData })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || res.statusText)
    return data
  },
  rawEmailUrl: (id) => `${BASE}/emails/${id}/raw`,
  attachmentDownloadUrl: (id) => `${BASE}/attachments/${id}/download`,
}
