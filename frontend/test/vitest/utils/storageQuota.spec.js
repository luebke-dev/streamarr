import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  API_CACHE_STORAGE_PREFIX,
  clearApiCacheStorage,
  isQuotaExceededError,
  setLocalStorageItem,
} from 'src/utils/storageQuota'
import { saveAuthTokens } from 'src/utils/authStorage'

const originalLocalStorage = globalThis.localStorage

function quotaError() {
  const error = new Error('The quota has been exceeded.')
  error.name = 'QuotaExceededError'
  error.code = 22
  return error
}

function installLocalStorage(initial = {}, setItemImpl = null) {
  const store = new Map(Object.entries(initial))
  const storage = {
    get length() {
      return store.size
    },
    key: vi.fn((index) => Array.from(store.keys())[index] ?? null),
    getItem: vi.fn((key) => store.get(String(key)) ?? null),
    setItem: vi.fn((key, value) => {
      if (setItemImpl) return setItemImpl(store, key, value)
      store.set(String(key), String(value))
      return undefined
    }),
    removeItem: vi.fn((key) => {
      store.delete(String(key))
    }),
    clear: vi.fn(() => {
      store.clear()
    }),
  }

  Object.defineProperty(globalThis, 'localStorage', {
    value: storage,
    writable: true,
    configurable: true,
  })

  return { storage, store }
}

afterEach(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: originalLocalStorage,
    writable: true,
    configurable: true,
  })
  originalLocalStorage.clear()
  vi.restoreAllMocks()
})

describe('isQuotaExceededError', () => {
  it('detects browser storage quota errors', () => {
    expect(isQuotaExceededError(quotaError())).toBe(true)
    expect(isQuotaExceededError(new Error('Network error'))).toBe(false)
  })
})

describe('clearApiCacheStorage', () => {
  it('removes only API cache entries', () => {
    const { store } = installLocalStorage({
      [`${API_CACHE_STORAGE_PREFIX}v2:a`]: 'cached',
      [`${API_CACHE_STORAGE_PREFIX}v1:b`]: 'cached',
      access_token: 'token',
    })

    expect(clearApiCacheStorage()).toBe(2)
    expect(store.has(`${API_CACHE_STORAGE_PREFIX}v2:a`)).toBe(false)
    expect(store.has(`${API_CACHE_STORAGE_PREFIX}v1:b`)).toBe(false)
    expect(store.get('access_token')).toBe('token')
  })
})

describe('setLocalStorageItem', () => {
  it('clears API cache and retries once when quota is exceeded', () => {
    let calls = 0
    const { store, storage } = installLocalStorage(
      {
        [`${API_CACHE_STORAGE_PREFIX}v2:old`]: 'cached',
        unrelated: 'keep',
      },
      (backingStore, key, value) => {
        calls += 1
        if (calls === 1) throw quotaError()
        backingStore.set(String(key), String(value))
      },
    )

    setLocalStorageItem('access_token', 'token')

    expect(storage.setItem).toHaveBeenCalledTimes(2)
    expect(store.has(`${API_CACHE_STORAGE_PREFIX}v2:old`)).toBe(false)
    expect(store.get('unrelated')).toBe('keep')
    expect(store.get('access_token')).toBe('token')
  })

  it('lets auth token storage recover from stale API cache entries', () => {
    let calls = 0
    const { store } = installLocalStorage(
      {
        [`${API_CACHE_STORAGE_PREFIX}v2:old`]: 'cached',
      },
      (backingStore, key, value) => {
        calls += 1
        if (calls === 1) throw quotaError()
        backingStore.set(String(key), String(value))
      },
    )

    saveAuthTokens('access', 'refresh')

    expect(store.has(`${API_CACHE_STORAGE_PREFIX}v2:old`)).toBe(false)
    expect(store.get('access_token')).toBe('access')
    expect(store.get('refresh_token')).toBe('refresh')
  })
})
