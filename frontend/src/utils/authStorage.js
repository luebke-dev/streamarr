import { setLocalStorageItem } from 'src/utils/storageQuota'

export const ACCESS_TOKEN_KEY = 'access_token'
export const REFRESH_TOKEN_KEY = 'refresh_token'
export const SERVER_URL_KEY = 'pyrate-server-url'

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
