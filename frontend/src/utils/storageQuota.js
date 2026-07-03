export const API_CACHE_STORAGE_PREFIX = 'pyrate:api-cache:'

export function isQuotaExceededError(error) {
  if (!error) return false

  return (
    error.name === 'QuotaExceededError' ||
    error.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
    error.code === 22 ||
    error.code === 1014 ||
    /quota|exceeded/i.test(error.message || '')
  )
}

function collectLocalStorageKeys(predicate) {
  if (typeof localStorage === 'undefined') return []

  const keys = new Set()

  if (typeof localStorage.length === 'number' && typeof localStorage.key === 'function') {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (key && predicate(key)) keys.add(key)
    }
  }

  for (const key of Object.keys(localStorage)) {
    if (predicate(key)) keys.add(key)
  }

  return Array.from(keys)
}

export function clearApiCacheStorage() {
  if (typeof localStorage === 'undefined') return 0

  const keys = collectLocalStorageKeys((key) => key.startsWith(API_CACHE_STORAGE_PREFIX))
  for (const key of keys) {
    localStorage.removeItem(key)
  }
  return keys.length
}

export function setLocalStorageItem(key, value, { clearApiCacheOnQuota = true } = {}) {
  if (typeof localStorage === 'undefined') return

  try {
    localStorage.setItem(key, value)
  } catch (error) {
    if (!clearApiCacheOnQuota || !isQuotaExceededError(error)) {
      throw error
    }

    clearApiCacheStorage()
    localStorage.setItem(key, value)
  }
}
