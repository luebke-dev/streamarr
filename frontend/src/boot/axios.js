import { defineBoot } from '#q-app/wrappers'
import axios from 'axios'
import { useAuthStore } from 'src/stores/auth'
import { getAccessToken, getServerUrl, isNativePlatform } from 'src/utils/authStorage'
import { logger } from 'src/utils/logger'

// Always read the server URL from localStorage (set by the user on the login page).
// Falls back to relative path ('') so dev proxy / same-origin deployments still work.
function getBaseURL() {
  return getServerUrl()
}

// On native platforms (Capacitor), use fetch adapter to leverage native HTTP
// which bypasses CORS and WebView restrictions.
const isNative = isNativePlatform()

const api = axios.create({
  baseURL: getBaseURL(),
  timeout: 10000,
  // Send the httpOnly refresh cookie (web build) on /api/auth/* requests.
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    // Tell the backend which token-delivery model to use: web ⇒ httpOnly
    // refresh cookie, native ⇒ refresh token in the response body.
    'X-Client-Platform': isNative ? 'native' : 'web',
  },
  ...(isNative ? { adapter: 'fetch' } : {}),
})

export default defineBoot(({ app, router }) => {
  const authStore = useAuthStore()

  // Request interceptor - add auth token to every request
  api.interceptors.request.use(
    (config) => {
      // Always re-read baseURL from localStorage so changes (e.g. after login or
      // settings update) take effect immediately without a full page reload.
      config.baseURL = getBaseURL()
      // Get token from localStorage directly to ensure it's always current
      // Don't overwrite if a custom Authorization header is already set (e.g. play tokens for stream API)
      const token = getAccessToken()
      if (token && !config.headers.Authorization) {
        config.headers.Authorization = `Bearer ${token}`
      }
      return config
    },
    (error) => {
      return Promise.reject(error)
    },
  )

  // Response interceptor with improved error handling
  api.interceptors.response.use(
    (response) => {
      return response
    },
    async (error) => {
      const originalRequest = error.config

      // Skip retry logic for auth endpoints to avoid infinite loops
      const isAuthEndpoint =
        originalRequest?.url?.includes('/auth/refresh') ||
        originalRequest?.url?.includes('/auth/status') ||
        originalRequest?.url?.includes('/auth/login') ||
        originalRequest?.url?.includes('/auth/logout')

      // Skip auth retry if explicitly requested or for stream endpoints
      // Stream endpoints use play tokens (not JWTs), so JWT refresh would be pointless
      const isStreamEndpoint = originalRequest?.url?.includes('/api/stream/')
      const skipAuthRetry = originalRequest?._skipAuthRetry || isStreamEndpoint

      // Handle 401 errors (unauthorized) with safety checks
      // Don't retry auth endpoints to prevent infinite loops
      if (
        error.response?.status === 401 &&
        !originalRequest._retry &&
        originalRequest &&
        !isAuthEndpoint &&
        !skipAuthRetry
      ) {
        originalRequest._retry = true

        try {
          // Attempt a refresh when we might have a live session: native holds a
          // JS refresh token; web relies on the httpOnly refresh cookie, so we
          // try whenever an access token was in play (the cookie decides).
          const canRefresh = isNative
            ? Boolean(authStore?.refreshToken)
            : Boolean(authStore?.accessToken)
          if (authStore && canRefresh) {
            await authStore.refreshAccessToken()

            // Retry the original request with new token
            const token = authStore.accessToken
            if (token && originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${token}`
              return api(originalRequest)
            }
          }
        } catch (refreshError) {
          logger.error('Token refresh failed:', refreshError)
          // Redirect to login if refresh fails
          if (authStore) {
            authStore.logout()
          }
          router.push('/auth/login')
          return Promise.reject(refreshError)
        }
      }

      // Handle 401 errors - redirect to login if not authenticated
      // But don't redirect for auth endpoints or stream endpoints (they use play tokens)
      if (error.response?.status === 401 && !isAuthEndpoint && !isStreamEndpoint) {
        // Log status/URL only — never the raw response body, which can carry
        // sensitive auth/billing detail and is written to the production console.
        logger.error('Authentication error:', error.response.status, originalRequest?.url)

        // Check if user is not authenticated and redirect to login
        if (authStore && !authStore.isAuthenticated) {
          router.push('/auth/login')
        }
      } else if (error.response?.status >= 500) {
        logger.error('Server error:', error.response.status, originalRequest?.url)
      }

      return Promise.reject(error)
    },
  )

  // for use inside Vue files (Options API) through this.$axios and this.$api
  // Point $axios at the configured `api` instance (not the raw axios import) so
  // Options-API callers can't accidentally bypass the auth/baseURL interceptors.
  app.config.globalProperties.$axios = api

  app.config.globalProperties.$api = api
  // ^ ^ ^ this will allow you to use this.$api (for Vue Options API form)
  //       so you can easily perform requests against your app's API
})

export { api }
