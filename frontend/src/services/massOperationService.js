import { api } from 'boot/axios'

const BASE = '/api/mass-operations'

export async function listMassOperations(params = {}) {
  const { data } = await api.get(BASE, { params })
  return data
}

export async function getMassOperation(guid) {
  const { data } = await api.get(`${BASE}/${guid}`)
  return data
}

export async function createMassOperation(payload) {
  const { data } = await api.post(BASE, payload)
  return data
}

export async function updateMassOperation(guid, payload) {
  const { data } = await api.patch(`${BASE}/${guid}`, payload)
  return data
}

export async function deleteMassOperation(guid) {
  await api.delete(`${BASE}/${guid}`)
}

export async function dryRunMassOperation(guid) {
  const { data } = await api.post(`${BASE}/${guid}/dry-run`)
  return data
}

export async function runMassOperationNow(guid) {
  const { data } = await api.post(`${BASE}/${guid}/run`)
  return data
}

export async function listMassOperationRuns(guid, limit = 20) {
  const { data } = await api.get(`${BASE}/${guid}/runs`, { params: { limit } })
  return data
}
