import { api } from 'boot/axios'

export async function getContinueWatching(params = {}) {
  const response = await api.get('/api/viewing-history/continue-watching', { params })
  return response.data
}

export async function getSimilarMedia(guid, limit, signal) {
  const response = await api.get(`/api/media/${guid}/similar`, {
    params: { limit },
    signal,
  })
  return response.data
}

export async function reportPlaybackProblem(mediaUuid, payload) {
  const response = await api.post(`/api/play/${mediaUuid}/report-problem`, payload)
  return response.data
}

export async function getBookViewingHistory(mediaGuid) {
  const response = await api.get('/api/viewing-history', {
    params: { content_type: 'book', content_guid: mediaGuid },
  })
  return response.data
}

export async function saveViewingHistory(payload) {
  const response = await api.post('/api/viewing-history', payload)
  return response.data
}

export async function getMyDevices(params = {}) {
  const response = await api.get('/api/devices/me', { params })
  return response.data
}

export async function discoverCastTargets(params = {}) {
  const response = await api.get('/api/cast/discover', { params })
  return response.data
}

export async function getAllMarkers(mediaId) {
  const response = await api.get(`/api/media/${mediaId}/markers/all`)
  return response.data
}

export async function updateMarker(markerGuid, payload) {
  const response = await api.put(`/api/media/markers/${markerGuid}`, payload)
  return response.data
}

export async function createMarker(mediaId, payload) {
  const response = await api.post(`/api/media/${mediaId}/markers`, payload)
  return response.data
}

export async function deleteMarker(markerGuid) {
  const response = await api.delete(`/api/media/markers/${markerGuid}`)
  return response.data
}

export async function detectMarkers(endpoint) {
  const response = await api.post(endpoint)
  return response.data
}

export async function searchMedia(payload) {
  const response = await api.post('/api/search/', payload)
  return response.data
}

export async function getGenresWithItems(params = {}) {
  const response = await api.get('/api/genres/with-items', { params })
  return response.data
}

export async function getGenres(params = {}) {
  const response = await api.get('/api/genres', { params })
  return response.data
}

export async function getShowResume(showGuid) {
  const response = await api.get(`/api/media/shows/${showGuid}/resume`)
  return response.data
}

export async function getPlatforms() {
  const response = await api.get('/api/platforms')
  return response.data
}

export async function getGamesLibraryConfig() {
  const response = await api.get('/api/libraries/games/config')
  return response.data
}
