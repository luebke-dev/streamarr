import { api } from 'boot/axios'

export async function getCurrentUser() {
  const response = await api.get('/api/auth/me')
  return response.data
}

export async function updateCurrentUser(payload) {
  const response = await api.put('/api/auth/me', payload)
  return response.data
}

export async function changeUserPassword(userGuid, payload) {
  const response = await api.put(`/api/users/${userGuid}/password`, payload)
  return response.data
}

export async function getParentalControl() {
  const response = await api.get('/api/users/me/parental-control')
  return response.data
}

export async function updateParentalControl(parentalMaxAge) {
  const response = await api.put('/api/users/me/parental-control', {
    parental_max_age: parentalMaxAge,
  })
  return response.data
}
