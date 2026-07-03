import { api } from 'boot/axios'

const BASE = '/api/smart-collections'

export async function listBuilders() {
  const { data } = await api.get(`${BASE}/builders`)
  return data
}

export async function listSmartCollections(params = {}) {
  const { data } = await api.get(BASE, { params })
  return data
}

export async function getSmartCollection(guid) {
  const { data } = await api.get(`${BASE}/${guid}`)
  return data
}

export async function createSmartCollection(payload) {
  const { data } = await api.post(BASE, payload)
  return data
}

export async function updateSmartCollection(guid, payload) {
  const { data } = await api.patch(`${BASE}/${guid}`, payload)
  return data
}

export async function deleteSmartCollection(guid) {
  await api.delete(`${BASE}/${guid}`)
}

export async function runSmartCollectionNow(guid) {
  const { data } = await api.post(`${BASE}/${guid}/run`)
  return data
}

export async function listSmartCollectionRuns(guid, limit = 20) {
  const { data } = await api.get(`${BASE}/${guid}/runs`, { params: { limit } })
  return data
}
