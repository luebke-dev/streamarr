import { setLocalStorageItem } from 'src/utils/storageQuota'

export const DEVICE_ID_KEY = 'pyrate_device_id'

export function generateDeviceId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0
    const value = char === 'x' ? random : (random & 0x3) | 0x8
    return value.toString(16)
  })
}

export function getStoredDeviceId() {
  return localStorage.getItem(DEVICE_ID_KEY)
}

export function getOrCreateDeviceId() {
  let deviceId = getStoredDeviceId()
  if (!deviceId) {
    deviceId = generateDeviceId()
    try {
      setLocalStorageItem(DEVICE_ID_KEY, deviceId)
    } catch {
      // A non-persisted device id is better than blocking the login screen.
    }
  }
  return deviceId
}

export function getDeviceInfo() {
  const userAgent = navigator.userAgent
  const platform = navigator.platform || 'Unknown'
  const language = navigator.language || 'Unknown'

  let browser = 'Unknown'
  if (userAgent.includes('Firefox')) {
    browser = 'Firefox'
  } else if (userAgent.includes('Chrome')) {
    browser = 'Chrome'
  } else if (userAgent.includes('Safari')) {
    browser = 'Safari'
  } else if (userAgent.includes('Edge')) {
    browser = 'Edge'
  }

  return {
    device_id: getOrCreateDeviceId(),
    browser,
    platform,
    language,
    user_agent: userAgent,
  }
}
