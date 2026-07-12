import { api } from 'boot/axios'

// --- Subscription packages ---

export async function getPackages(params = {}) {
  const response = await api.get('/api/subscriptions/packages', { params })
  return response.data
}

export async function getPackage(guid) {
  const response = await api.get(`/api/subscriptions/packages/${guid}`)
  return response.data
}

export async function createPackage(payload) {
  const response = await api.post('/api/subscriptions/packages', payload)
  return response.data
}

export async function updatePackage(guid, payload) {
  const response = await api.put(`/api/subscriptions/packages/${guid}`, payload)
  return response.data
}

export async function deletePackage(guid) {
  const response = await api.delete(`/api/subscriptions/packages/${guid}`)
  return response.data
}

export async function getStripeConfig() {
  const response = await api.get('/api/subscriptions/stripe-config')
  return response.data
}

// --- Groups ---

export async function getGroups() {
  const response = await api.get('/api/groups')
  return response.data
}

// --- Plugins ---

export async function getPluginRuntimePolicy() {
  const response = await api.get('/api/plugins/runtime-policy')
  return response.data
}

export async function getPluginRepositories() {
  const response = await api.get('/api/plugins/repositories')
  return response.data
}

export async function getInstalledPlugins() {
  const response = await api.get('/api/plugins/installed')
  return response.data
}

export async function getPluginValidation() {
  const response = await api.get('/api/plugins/validation')
  return response.data
}

export async function syncPluginRepository(repositoryId) {
  const response = await api.post(`/api/plugins/repositories/${repositoryId}/sync`)
  return response.data
}

// --- Vouchers ---

export async function getVouchers() {
  const response = await api.get('/api/vouchers')
  return response.data
}

export async function createVoucher(payload) {
  const response = await api.post('/api/vouchers', payload)
  return response.data
}

export async function batchCreateVouchers(payload) {
  const response = await api.post('/api/vouchers/batch', payload)
  return response.data
}

export async function updateVoucher(guid, payload) {
  const response = await api.patch(`/api/vouchers/${guid}`, payload)
  return response.data
}

export async function deleteVoucher(guid) {
  const response = await api.delete(`/api/vouchers/${guid}`)
  return response.data
}

export async function exportVouchersCsv() {
  const response = await api.get('/api/vouchers/export.csv', { responseType: 'blob' })
  return response.data
}

// --- Sessions ---

export async function getSessions() {
  const response = await api.get('/api/sessions')
  return response.data
}

export async function getActiveDeviceSessions() {
  const response = await api.get('/api/devices/sessions/active')
  return response.data
}

export async function getDeviceSessionContract(deviceGuid) {
  const response = await api.get(`/api/devices/${deviceGuid}/session`)
  return response.data
}

export async function terminateAllSessions() {
  const response = await api.delete('/api/sessions')
  return response.data
}

export async function terminateSession(sessionId) {
  const response = await api.delete(`/api/sessions/${sessionId}`)
  return response.data
}

export async function cleanupSessions() {
  const response = await api.post('/api/sessions/cleanup')
  return response.data
}

export async function getSessionLogs(sessionId, params = {}) {
  const response = await api.get(`/api/sessions/${sessionId}/logs`, { params })
  return response.data
}

export async function getActivityLogs(params = {}) {
  const response = await api.get('/api/activity-logs', { params })
  return response.data
}

// --- Watch parties (admin) ---

export async function getAdminParties() {
  const response = await api.get('/api/parties/admin/all')
  return response.data
}

export async function endAdminParty(guid) {
  const response = await api.delete(`/api/parties/admin/${guid}`)
  return response.data
}

// --- Tasks ---

export async function getTasks() {
  const response = await api.get('/api/tasks')
  return response.data
}

export async function runTask(taskId) {
  const response = await api.post(`/api/tasks/${taskId}/run`)
  return response.data
}

export async function getTaskHistory(params = {}) {
  const response = await api.get('/api/tasks/history', { params })
  return response.data
}

export async function getTaskRun(runId) {
  const response = await api.get(`/api/tasks/history/${runId}`)
  return response.data
}

// --- Settings ---

export async function getFavoritesSettings() {
  const response = await api.get('/api/settings/favorites')
  return response.data
}

export async function saveFavoritesSettings(payload) {
  const response = await api.put('/api/settings/favorites', payload)
  return response.data
}

export async function getAutomationSettings() {
  const response = await api.get('/api/settings/automation')
  return response.data
}

export async function saveAutomationSettings(payload) {
  const response = await api.put('/api/settings/automation', payload)
  return response.data
}

export async function getOidcSettings() {
  const response = await api.get('/api/settings/oidc')
  return response.data
}

export async function saveOidcSettings(payload) {
  const response = await api.put('/api/settings/oidc', payload)
  return response.data
}

export async function getPermissionDefaults() {
  const response = await api.get('/api/settings/permissions')
  return response.data
}

export async function savePermissionDefaults(payload) {
  const response = await api.put('/api/settings/permissions', payload)
  return response.data
}

// --- Backups ---

export async function getSettingsBackup() {
  const response = await api.get('/api/backups/settings')
  return response.data
}

export async function getDatabaseBackup() {
  const response = await api.get('/api/backups/database')
  return response.data
}

export async function restoreDatabaseBackup(payload) {
  const response = await api.post('/api/backups/database/restore', payload)
  return response.data
}

export async function restoreSettingsBackup(payload) {
  const response = await api.post('/api/backups/settings/restore', payload)
  return response.data
}
