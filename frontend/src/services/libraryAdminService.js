import { api } from 'boot/axios'

// ---- Library type / plugin / metadata-provider discovery ----

export async function getLibraryTypes() {
  const response = await api.get('/api/libraries/types')
  return response.data
}

export async function getLibraryPlugins(libraryType) {
  const response = await api.get('/api/libraries/plugins', {
    params: { library_type: libraryType },
  })
  return response.data
}

export async function getLibraryMetadataProviders(libraryType) {
  const response = await api.get('/api/libraries/metadata-providers', {
    params: { library_type: libraryType },
  })
  return response.data
}

// ---- Library CRUD ----

export async function createLibrary(payload) {
  const response = await api.post('/api/libraries', payload)
  return response.data
}

export async function getLibrary(libraryId) {
  const response = await api.get(`/api/libraries/${libraryId}`)
  return response.data
}

export async function deleteLibrary(libraryId) {
  const response = await api.delete(`/api/libraries/${libraryId}`)
  return response.data
}

// ---- Per-type library config + naming ----
// `type` is the lowercase media type, e.g. "movies".

export async function getLibraryConfig(type) {
  const response = await api.get(`/api/libraries/${type}/config`)
  return response.data
}

export async function saveLibraryConfig(type, payload) {
  const response = await api.put(`/api/libraries/${type}/config`, payload)
  return response.data
}

export async function previewNaming(type, payload) {
  const response = await api.post(`/api/libraries/${type}/preview-naming`, payload)
  return response.data
}

// ---- Scoring ----

export async function getScoring(type) {
  const response = await api.get(`/api/libraries/${type}/scoring`)
  return response.data
}

export async function saveScoring(type, config) {
  const response = await api.put(`/api/libraries/${type}/scoring`, config)
  return response.data
}

export async function resetScoring(type) {
  const response = await api.post(`/api/libraries/${type}/scoring/reset`)
  return response.data
}

// ---- Quality profiles (Sonarr-style ordered list + cutoff) ----

export async function getQualityLadder(type) {
  const response = await api.get(`/api/libraries/quality-profiles/${type}/qualities`)
  return response.data
}

export async function getQualityProfile(type, params) {
  const response = await api.get(
    `/api/libraries/quality-profiles/${type}`,
    params ? { params } : undefined,
  )
  return response.data
}

export async function saveQualityProfile(type, payload, favorites) {
  const response = await api.put(`/api/libraries/quality-profiles/${type}`, payload, {
    params: { favorites },
  })
  return response.data
}

export async function resetQualityProfile(type, favorites) {
  const response = await api.post(`/api/libraries/quality-profiles/${type}/reset`, null, {
    params: { favorites },
  })
  return response.data
}

// ---- Platform options ----

export async function getPlatforms() {
  const response = await api.get('/api/platforms')
  return response.data
}

// ---- Metadata providers (admin config) ----

export async function getMetadataProviders() {
  const response = await api.get('/api/metadata/providers')
  return response.data
}

export async function getMetadataProviderConfig(domain) {
  const response = await api.get(`/api/metadata/providers/${domain}/config`)
  return response.data
}

export async function saveMetadataProviderConfig(domain, config) {
  const response = await api.put(`/api/metadata/providers/${domain}/config`, { config })
  return response.data
}

export async function testMetadataProviderConnection(domain, config) {
  const url = `/api/metadata/providers/${domain}/test`
  const response = config ? await api.post(url, { config }) : await api.post(url)
  return response.data
}

// ---- Transcoding settings ----

export async function getTranscodingSettings() {
  const response = await api.get('/api/settings/transcoding')
  return response.data
}

export async function saveTranscodingSettings(payload) {
  const response = await api.put('/api/settings/transcoding', payload)
  return response.data
}

export async function getComputingStatus() {
  const response = await api.get('/api/computing/status')
  return response.data
}
