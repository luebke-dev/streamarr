import { setLocalStorageItem } from 'src/utils/storageQuota'

export const ACCESS_TOKEN_KEY = 'access_token'
export const REFRESH_TOKEN_KEY = 'refresh_token'
export const SERVER_URL_KEY = 'pyrate-server-url'

// Token storage model — differs by platform so the web build is not exposed to
// the localStorage XSS-exfiltration vector:
//
//  • Web: the refresh token lives ONLY in a backend-set httpOnly/Secure cookie
//    that JavaScript cannot read; the short-lived access token is held in a
//    module-local variable (memory), never persisted. A page reload drops the
//    in-memory access token and the app silently mints a new one from the
//    cookie at startup (see auth store initialize()).
//  • Native (Tauri/Capacitor): there is no shared cookie jar with the backend,
//    so both tokens are persisted in the app's localStorage as before.
//
// The switch is `isNativePlatform()`; the backend mirrors it via the
// `X-Client-Platform` header (see boot/axios.js) to decide cookie vs. body.

export function isNativePlatform() {
  return Boolean(
    typeof window !== 'undefined' && window.Capacitor?.isNativePlatform?.(),
  )
}

// In-memory access token for the web build (not persisted).
let memoryAccessToken = null

export function getAccessToken() {
  if (isNativePlatform()) {
    return localStorage.getItem(ACCESS_TOKEN_KEY)
  }
  return memoryAccessToken
}

export function getRefreshToken() {
  // Web: the refresh token is an httpOnly cookie, not reachable from JS.
  if (isNativePlatform()) {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  }
  return null
}

export function saveAuthTokens(accessToken, refreshToken) {
  if (isNativePlatform()) {
    try {
      setLocalStorageItem(ACCESS_TOKEN_KEY, accessToken)
      setLocalStorageItem(REFRESH_TOKEN_KEY, refreshToken)
    } catch (error) {
      clearAuthTokens()
      throw error
    }
    return
  }
  // Web: keep only the access token, in memory. The refresh token (if any) is
  // ignored here because it is delivered as an httpOnly cookie by the backend.
  memoryAccessToken = accessToken || null
}

export function clearAuthTokens() {
  memoryAccessToken = null
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function getServerUrl(fallback = '') {
  return localStorage.getItem(SERVER_URL_KEY) || fallback
}

export function setServerUrl(url) {
  setLocalStorageItem(SERVER_URL_KEY, url)
}

// Shared backend-URL builder used by both the auth store (OIDC login) and the
// OIDC callback page. Resolves the configured server URL (falling back to the
// current origin) and returns the URL object plus a serializer that emits an
// absolute href when an explicit server is configured (native builds) or a
// relative path for same-origin web deployments. Mutate the returned `url`
// (e.g. url.searchParams.set(...)) before calling toHref().
export function buildServerUrl(path) {
  const baseUrl = getServerUrl().replace(/\/+$/, '')
  const useAbsolute = Boolean(baseUrl)
  const url = new URL(`${baseUrl || window.location.origin}${path}`)
  return {
    url,
    toHref: () => (useAbsolute ? url.toString() : `${url.pathname}${url.search}`),
  }
}
