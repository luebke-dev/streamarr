import { api } from 'boot/axios'

export async function getFriends() {
  const response = await api.get('/api/friends')
  return response.data
}

export async function getPendingFriendRequests() {
  const response = await api.get('/api/friends/pending')
  return response.data
}

export async function getSentFriendRequests() {
  const response = await api.get('/api/friends/sent')
  return response.data
}

export async function getCurrentUser() {
  const response = await api.get('/api/auth/me')
  return response.data
}

export async function sendFriendRequest(email) {
  const response = await api.post('/api/friends/request', { email })
  return response.data
}

export async function acceptFriendRequest(guid) {
  const response = await api.post(`/api/friends/${guid}/accept`)
  return response.data
}

export async function rejectFriendRequest(guid) {
  const response = await api.post(`/api/friends/${guid}/reject`)
  return response.data
}

export async function deleteFriendship(guid) {
  const response = await api.delete(`/api/friends/${guid}`)
  return response.data
}

export async function getInvites() {
  const response = await api.get('/api/invites')
  return response.data
}

export async function createInvite(payload = { expiry_hours: 168, max_uses: 1 }) {
  const response = await api.post('/api/invites', payload)
  return response.data
}

export async function deleteInvite(guid) {
  const response = await api.delete(`/api/invites/${guid}`)
  return response.data
}
