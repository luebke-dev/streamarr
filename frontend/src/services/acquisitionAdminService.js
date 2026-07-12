import { api } from 'boot/axios'

// --- Downloads ---

export async function listDownloads() {
  const response = await api.get('/api/downloads')
  return response.data
}

export async function setDownloadPaused(guid, pause) {
  const response = await api.post(`/api/downloads/${guid}/${pause ? 'pause' : 'resume'}`)
  return response.data
}

export async function deleteDownload(guid) {
  const response = await api.delete(`/api/downloads/${guid}`)
  return response.data
}

// --- Downloaders ---

export async function listDownloaders() {
  const response = await api.get('/api/downloaders')
  return response.data
}

export async function getDownloaderTypes() {
  const response = await api.get('/api/downloaders/types')
  return response.data
}

export async function createDownloader(payload) {
  const response = await api.post('/api/downloaders', payload)
  return response.data
}

export async function updateDownloader(guid, payload) {
  const response = await api.put(`/api/downloaders/${guid}`, payload)
  return response.data
}

export async function deleteDownloader(guid) {
  const response = await api.delete(`/api/downloaders/${guid}`)
  return response.data
}

// --- Indexers ---

export async function listIndexers() {
  const response = await api.get('/api/indexers')
  return response.data
}

export async function getIndexer(guid) {
  const response = await api.get(`/api/indexers/${guid}`)
  return response.data
}

export async function fetchIndexerCaps(payload) {
  const response = await api.post('/api/indexers/caps', payload)
  return response.data
}

export async function createIndexer(payload) {
  const response = await api.post('/api/indexers/', payload)
  return response.data
}

export async function updateIndexer(guid, payload) {
  const response = await api.put(`/api/indexers/${guid}`, payload)
  return response.data
}

export async function deleteIndexer(guid) {
  const response = await api.delete(`/api/indexers/${guid}`)
  return response.data
}

// --- Admin dashboard aggregates ---

export async function getSystemSettings() {
  const response = await api.get('/api/settings/system')
  return response.data
}

export async function getStorageOverview() {
  const response = await api.get('/api/settings/storage/overview')
  return response.data
}

export async function listUsers() {
  const response = await api.get('/api/users')
  return response.data
}

export async function getOnlineUsers() {
  const response = await api.get('/api/users/online')
  return response.data
}

export async function getMedia(params) {
  const response = await api.get('/api/media', { params })
  return response.data
}

export async function listSessions() {
  const response = await api.get('/api/sessions')
  return response.data
}

export async function listLibraries(params) {
  const response = await api.get('/api/libraries', { params })
  return response.data
}
