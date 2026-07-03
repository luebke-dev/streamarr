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
