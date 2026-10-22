import { defineBoot } from '#q-app/wrappers'
import axios from 'axios'
import { useAuthStore } from 'src/stores/auth'
import { getAccessToken, getServerUrl, isNativePlatform } from 'src/utils/authStorage'
import { isDesktopApp } from 'src/utils/desktopPlatform'
import { installShellTransport } from 'src/utils/shellTransport'
import { invoke } from '@tauri-apps/api/core'
import { logger } from 'src/utils/logger'

// On the desktop the shell performs the requests. Two reasons, both measured: the
// webview cannot reach the server at all (the name resolves to an address that does not
// answer, and the IP pin that fixes it belongs to the shell), and credentials should not
// exist in two places. Outside the desktop app this is a no-op, so the browser build is
// unchanged.
installShellTransport()

/** Whether the shell is holding this session's credentials. */
const usesShellTokens = isDesktopApp()

/**
 * Hands tokens to the shell so they are stored in the OS keyring rather than here.
 *
 * The page receives them as part of a login or refresh response — it has to, since it
 * performs those calls — but persisting them in `localStorage` is what the shell's
 * keyring work exists to avoid. After this call the page keeps nothing durable, and a
 * restart restores the session from the keyring.
 */
async function handTokensToShell(data) {
  if (!usesShellTokens || !data || typeof data !== 'object') return
  if (!data.access_token && !data.refresh_token) return
  try {
    await invoke('store_tokens', {
      tokens: {
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        token_type: data.token_type,
        expires_in: data.expires_in,
      },
    })
  } catch (error) {
    // Not fatal to the request that produced the tokens, but it must not be silent: a
    // session that is not stored is one that vanishes on restart, which is the exact
    // bug this whole path exists to prevent.
    logger.error('Token konnten nicht im Schlüsselbund gespeichert werden:', error)
  }
}

// Always read the server URL from localStorage (set by the user on the login page).
// Falls back to relative path ('') so dev proxy / same-origin deployments still work.
function getBaseURL() {
  return getServerUrl()
}

// On native platforms (Capacitor), use fetch adapter to leverage native HTTP
// which bypasses CORS and WebView restrictions.
const isNative = isNativePlatform()
// The desktop shell performs every API call, but it does so by replacing
// `globalThis.fetch` — and axios defaults to **XHR**, which never goes through that
// replacement. Measured: the login page's requests left the webview itself, the server
// logged a CORS preflight (`OPTIONS /api/auth/background`) answered with 400, and the
// app showed a network error while the shell's own requests kept succeeding. The fetch
// adapter is what makes axios use the shell at all.
const usesShellTransport = isDesktopApp()

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
  ...(isNative || usesShellTransport ? { adapter: 'fetch' } : {}),
})

// The default instance matters too, and this is not cosmetic: the login page calls
// `axios.get(...)` on the *global* axios, not on `api`. Without this line those calls
// still went out as XHR from the webview — measured after the first fix: 144 requests
// and 48 CORS preflights with a WebKit user agent in five minutes, next to the shell's
// own. CORS then rejects the response and the user sees a network error.
if (usesShellTransport) {
  axios.defaults.adapter = 'fetch'
}

/**
 * Clears the shell's stored tokens.
 *
 * Called by the auth store on sign-out. Without it the next start would restore the
 * session the user just ended, because the keyring copy would still be there.
 */
export async function forgetShellTokens() {
  if (!usesShellTokens) return
  try {
    await invoke('forget_tokens')
  } catch (error) {
    logger.error('Token konnten nicht entfernt werden:', error)
  }
}

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
      // A login or refresh response carries fresh tokens; the shell stores them.
      handTokensToShell(response?.data)
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
          // Attempt a refresh when we might have a live session. Native holds a
          // JS refresh token, so we can check for it. Web keeps only an
          // in-memory access token and an httpOnly refresh cookie that JS cannot
          // read — so we must always *try*: on a cold load the access token has
          // not been minted from the cookie yet, and gating on it would let those
          // first requests fail instead of being retried. The cookie decides; if
          // there is none the refresh 401s and we fall through to logout below.
          // Concurrent 401s share one refresh via the store's refreshPromise.
          const canRefresh = isNative ? Boolean(authStore?.refreshToken) : true
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
