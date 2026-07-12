import { api } from 'boot/axios'

export async function redeemVoucher(code) {
  const response = await api.post('/api/vouchers/redeem', { code })
  return response.data
}

export async function createSetupIntent() {
  const response = await api.post('/api/subscriptions/setup-intent')
  return response.data
}
