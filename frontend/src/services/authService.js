import { api } from 'boot/axios'

export async function validateInvite(token) {
  const response = await api.post('/api/invites/validate', { token })
  return response.data
}

export async function registerWithInvite(payload) {
  const response = await api.post('/api/auth/register', payload)
  return response.data
}

// Public, enumeration-safe resend of the email-verification link.
export async function resendVerification(email) {
  const response = await api.post('/api/auth/resend-verification', { email })
  return response.data
}

export async function forgotPassword(email) {
  const response = await api.post('/api/auth/forgot-password', { email })
  return response.data
}

export async function resetPassword(payload) {
  const response = await api.post('/api/auth/reset-password', payload)
  return response.data
}

export async function verifyEmail(token) {
  const response = await api.get('/api/auth/verify-email', { params: { token } })
  return response.data
}

export async function getInstallStatus() {
  const response = await api.get('/api/install/status')
  return response.data
}

export async function setupInstall(payload) {
  const response = await api.post('/api/install/setup', payload)
  return response.data
}
