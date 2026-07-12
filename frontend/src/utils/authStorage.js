import { setLocalStorageItem } from 'src/utils/storageQuota'

export const ACCESS_TOKEN_KEY = 'access_token'
export const REFRESH_TOKEN_KEY = 'refresh_token'
export const SERVER_URL_KEY = 'pyrate-server-url'

// SECURITY TRADE-OFF (see auth findings): the access and (long-lived) refresh
// tokens are persisted in localStorage so the session survives page reloads and
// so the Tauri/Capacitor native builds — which have no shared httpOnly cookie
// jar with the backend — can authenticate. localStorage is readable by any
// script in the origin, so a single XSS can exfiltrate the refresh token.
// The proper fix is a backend-set httpOnly, Secure, SameSite=strict cookie for
// the refresh token (web build) plus a short-lived in-memory access token, with
// localStorage gated behind the native targets only. That is a coordinated
// backend + client change and is intentionally NOT done here; keep the token
// keys and access surface centralized in this module so that migration is a
// single-file change on the client side.

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function saveAuthTokens(accessToken, refreshToken) {
  try {
    setLocalStorageItem(ACCESS_TOKEN_KEY, accessToken)
    setLocalStorageItem(REFRESH_TOKEN_KEY, refreshToken)
  } catch (error) {
    clearAuthTokens()
    throw error
  }
}

export function clearAuthTokens() {
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
