import { api } from 'boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { getAccessToken, getServerUrl } from 'src/utils/authStorage'
import { logger } from 'src/utils/logger'
import { clearApiCacheStorage, isQuotaExceededError } from 'src/utils/storageQuota'

// Bumped when the response shape of a cached endpoint changes so old
// localStorage entries don't keep serving stale data. Last bump:
// persistent entries now carry their cache key for targeted invalidation.
const STORAGE_PREFIX = 'pyrate:api-cache:v3:'
const MEMORY_CACHE_MAX_ENTRIES = 200
const memoryCache = new Map()
const pendingRequests = new Map()

function stableStringify(value) {
  if (value == null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(',')}}`
}

function simpleHash(value) {
  let hash = 5381
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 33) ^ value.charCodeAt(i)
  }
  return (hash >>> 0).toString(36)
}

function userScope() {
  try {
    const userGuid = useAuthStore().user?.guid
    if (userGuid) return String(userGuid)
  } catch (error) {
    logger.debug('API cache user scope unavailable', error)
  }
  const token = getAccessToken() || ''
  return token ? simpleHash(token) : 'anonymous'
}

function makeCacheKey(method, url, payload) {
  return [
    method.toUpperCase(),
    getServerUrl() || 'same-origin',
    userScope(),
    url,
    stableStringify(payload || {}),
  ].join('|')
}

function readPersistentEntry(key) {
  if (typeof localStorage === 'undefined') return null
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${simpleHash(key)}`)
    return raw ? JSON.parse(raw) : null
  } catch (error) {
    logger.debug('API cache read failed', error)
    return null
  }
}

function writePersistentEntry(key, entry) {
  if (typeof localStorage === 'undefined') return
  const serialized = JSON.stringify({ ...entry, key })
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${simpleHash(key)}`, serialized)
  } catch (error) {
    if (isQuotaExceededError(error)) {
      try {
        clearApiCacheStorage()
        localStorage.setItem(`${STORAGE_PREFIX}${simpleHash(key)}`, serialized)
      } catch (retryError) {
        logger.debug('API cache write failed after quota cleanup', retryError)
      }
      return
    }
    logger.debug('API cache write failed', error)
  }
}

function readCache(key) {
  return memoryCache.get(key) || readPersistentEntry(key)
}

function writeCache(key, data, ttlMs, staleTtlMs, persist) {
  const now = Date.now()
  const entry = {
    data,
    expiresAt: now + ttlMs,
    staleAt: now + staleTtlMs,
  }
  memoryCache.delete(key)
  memoryCache.set(key, entry)
  while (memoryCache.size > MEMORY_CACHE_MAX_ENTRIES) {
    memoryCache.delete(memoryCache.keys().next().value)
  }
  if (persist) writePersistentEntry(key, entry)
}

async function cachedApiRequest(
  method,
  url,
  dataOrConfig = {},
  configOrOptions = {},
  maybeOptions = {},
) {
  const isGet = method.toLowerCase() === 'get'
  const config = isGet ? dataOrConfig || {} : configOrOptions || {}
  const body = isGet ? null : dataOrConfig || {}
  const options = isGet ? configOrOptions || {} : maybeOptions || {}
  const ttlMs = options.ttlMs ?? 60_000
  const staleTtlMs = options.staleTtlMs ?? 10 * 60_000
  const persist = options.persist !== false
  const cacheKey = makeCacheKey(method, url, {
    params: config.params || {},
    body,
  })
  const now = Date.now()
  const cached = readCache(cacheKey)

  if (cached && cached.expiresAt > now) {
    return { data: cached.data, cached: true, stale: false }
  }

  const refresh = async () => {
    const response = isGet ? await api.get(url, config) : await api.post(url, body, config)
    writeCache(cacheKey, response.data, ttlMs, staleTtlMs, persist)
    options.onRefresh?.(response.data)
    return response
  }

  if (cached && cached.staleAt > now) {
    if (!pendingRequests.has(cacheKey)) {
      pendingRequests.set(
        cacheKey,
        refresh()
          .catch((error) => {
            logger.debug('API cache background refresh failed', error)
          })
          .finally(() => pendingRequests.delete(cacheKey)),
      )
    }
    return { data: cached.data, cached: true, stale: true }
  }

  if (!pendingRequests.has(cacheKey)) {
    pendingRequests.set(
      cacheKey,
      refresh().finally(() => pendingRequests.delete(cacheKey)),
    )
  }
  return pendingRequests.get(cacheKey)
}

export function cachedApiGet(url, config = {}, options = {}) {
  return cachedApiRequest('get', url, config, options)
}

export function cachedApiPost(url, data = {}, config = {}, options = {}) {
  return cachedApiRequest('post', url, data, config, options)
}

function keyMatchesResource(key, match) {
  if (key.includes(match)) return true
  const url = key.split('|')[3] || ''
  return Boolean(url) && match.startsWith(`${url}/`)
}

export function invalidateApiCache(match) {
  const predicate = typeof match === 'function' ? match : (key) => keyMatchesResource(key, match)
  for (const key of Array.from(memoryCache.keys())) {
    if (predicate(key)) memoryCache.delete(key)
  }
  if (typeof localStorage === 'undefined') return
  for (const storageKey of Object.keys(localStorage)) {
    if (!storageKey.startsWith(STORAGE_PREFIX)) continue
    try {
      const entry = JSON.parse(localStorage.getItem(storageKey))
      if (!entry?.key || predicate(entry.key)) localStorage.removeItem(storageKey)
    } catch (error) {
      logger.debug('API cache invalidation dropped unreadable entry', error)
      localStorage.removeItem(storageKey)
    }
  }
}
