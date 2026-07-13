import { api } from 'boot/axios'

const BASE = '/api/overlays'

export async function listOverlayTemplates(params = {}) {
  const { data } = await api.get(BASE, { params })
  return data
}

export async function getOverlayTemplate(guid) {
  const { data } = await api.get(`${BASE}/${guid}`)
  return data
}

export async function createOverlayTemplate(payload) {
  const { data } = await api.post(BASE, payload)
  return data
}

export async function updateOverlayTemplate(guid, payload) {
  const { data } = await api.patch(`${BASE}/${guid}`, payload)
  return data
}

export async function deleteOverlayTemplate(guid) {
  await api.delete(`${BASE}/${guid}`)
}

export async function applyOverlay(mediaGuid, target = 'POSTER') {
  const { data } = await api.post(`${BASE}/apply/${mediaGuid}`, null, {
    params: { target },
  })
  return data
}

export function overlayPreviewUrl(mediaGuid, target = 'POSTER') {
  // Returns a URL that streams a rendered preview image when used as
  // an <img src=…>. The axios boot already attaches auth headers via
  // interceptor, but image elements can't carry them — streamarr's auth
  // also supports a cookie token, so the same-origin <img> works.
  return `/api/overlays/preview/${mediaGuid}?target=${encodeURIComponent(target)}`
}

export async function rerenderOverlayTemplate(guid) {
  const { data } = await api.post(`${BASE}/${guid}/rerender`)
  return data
}
