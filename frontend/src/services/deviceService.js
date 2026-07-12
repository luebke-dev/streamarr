import { api } from 'boot/axios'

export async function getMyDevices() {
  const response = await api.get('/api/devices/me')
  return response.data.items || []
}

export async function updateMyDevice(guid, payload) {
  const response = await api.put(`/api/devices/me/${guid}`, payload)
  return response.data
}

export async function removeMyDevice(guid) {
  const response = await api.delete(`/api/devices/me/${guid}`)
  return response.data
}

// ── Admin device management (all devices) ────────────────────────────────

export async function listDevices(params) {
  const response = await api.get('/api/devices', { params })
  return response.data
}

export async function deleteDevice(guid, permanent) {
  const response = await api.delete(`/api/devices/${guid}`, {
    params: { permanent },
  })
  return response.data
}

export async function updateDevice(guid, payload) {
  const response = await api.put(`/api/devices/${guid}`, payload)
  return response.data
}

export async function getDeviceSession(guid) {
  const response = await api.get(`/api/devices/${guid}/session`)
  return response.data
}
