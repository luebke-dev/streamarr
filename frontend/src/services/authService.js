import { api } from 'boot/axios'

export async function validateInvite(token) {
  const response = await api.post('/api/invites/validate', { token })
  return response.data
}

export async function registerWithInvite(payload) {
  const response = await api.post('/api/auth/register', payload)
  return response.data
}
