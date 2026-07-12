import { api } from 'boot/axios'

// --- Persons ---
export async function getPerson(guid) {
  const response = await api.get(`/api/persons/${guid}`)
  return response.data
}

export async function getPersonCredits(guid) {
  const response = await api.get(`/api/persons/${guid}/credits`)
  return response.data
}

export async function importPersonFilmography(guid) {
  const response = await api.post(`/api/persons/${guid}/import-filmography?force=true`)
  return response.data
}

// --- Media list / page layouts ---
export async function getShowResume(guid) {
  const response = await api.get(`/api/media/shows/${guid}/resume`)
  return response.data
}

// Returns the full axios response to mirror cachedApiGet's return shape, since
// callers read `response.data`. Extra args (cache options) are ignored, matching
// the previous `api.get` usage.
export function fetchPageLayoutViaApi(url, config) {
  return api.get(url, config)
}

export async function searchGamesIgdb(query) {
  const response = await api.post('/api/games/search-igdb', { query })
  return response.data
}

// --- Viewing history ---
export async function getViewingHistory(params) {
  const response = await api.get('/api/viewing-history', { params })
  return response.data
}

export async function deleteViewingHistoryItem(guid) {
  const response = await api.delete(`/api/viewing-history/${guid}`)
  return response.data
}

// --- Users ---
export async function deleteUser(guid) {
  const response = await api.delete(`/api/users/${guid}`)
  return response.data
}
