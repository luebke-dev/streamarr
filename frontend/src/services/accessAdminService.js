import { api } from 'boot/axios'

// --- Users ---

export async function getUsers() {
  const response = await api.get('/api/users')
  return response.data
}

export async function getUser(guid) {
  const response = await api.get(`/api/users/${guid}`)
  return response.data
}

export async function createUser(userData) {
  const response = await api.post('/api/users', userData)
  return response.data
}

export async function updateUser(guid, userData) {
  const response = await api.put(`/api/users/${guid}`, userData)
  return response.data
}

export async function updateUserPassword(guid, payload) {
  const response = await api.put(`/api/users/${guid}/password`, payload)
  return response.data
}

export async function deleteUser(guid) {
  const response = await api.delete(`/api/users/${guid}`)
  return response.data
}

// --- User permission overrides ---

export async function getUserPermissionOverrides(guid) {
  const response = await api.get(`/api/users/${guid}/permission-overrides`)
  return response.data
}

export async function updateUserPermissionOverrides(guid, payload) {
  const response = await api.put(`/api/users/${guid}/permission-overrides`, payload)
  return response.data
}

// --- User playback preferences ---

export async function getUserPlaybackPreferences(guid) {
  const response = await api.get(`/api/users/${guid}/playback-preferences`)
  return response.data
}

export async function updateUserPlaybackPreferences(guid, payload) {
  const response = await api.put(`/api/users/${guid}/playback-preferences`, payload)
  return response.data
}

// --- Groups ---

export async function getGroups() {
  const response = await api.get('/api/groups')
  return response.data
}

export async function getGroup(guid) {
  const response = await api.get(`/api/groups/${guid}`)
  return response.data
}

export async function createGroup(payload) {
  const response = await api.post('/api/groups', payload)
  return response.data
}

export async function updateGroup(guid, payload) {
  const response = await api.patch(`/api/groups/${guid}`, payload)
  return response.data
}

export async function deleteGroup(guid) {
  const response = await api.delete(`/api/groups/${guid}`)
  return response.data
}

export async function getUserEffectivePermissions(guid) {
  const response = await api.get(`/api/groups/user/${guid}/effective-permissions`)
  return response.data
}

// --- Invites ---

export async function getInvites(params) {
  const response = await api.get('/api/invites', { params })
  return response.data
}

export async function createInvite(inviteData) {
  const response = await api.post('/api/invites', inviteData)
  return response.data
}

export async function updateInvite(guid, inviteData) {
  const response = await api.put(`/api/invites/${guid}`, inviteData)
  return response.data
}

export async function deleteInvite(guid) {
  const response = await api.delete(`/api/invites/${guid}`)
  return response.data
}

export async function cleanupInvites() {
  const response = await api.post('/api/invites/cleanup')
  return response.data
}
