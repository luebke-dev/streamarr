import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from 'src/boot/axios'
import {
  clearAuthTokens,
  getAccessToken,
  getRefreshToken,
  getServerUrl,
  saveAuthTokens,
} from 'src/utils/authStorage'
import { getDeviceInfo, getOrCreateDeviceId } from 'src/utils/deviceIdentity'
import { logger } from 'src/utils/logger'
import { sanitizeRedirect } from 'src/utils/redirect'

export const useAuthStore = defineStore('auth', () => {
  // State
  const user = ref(null)
  const accessToken = ref(null)
  const refreshToken = ref(null)
  const deviceId = ref(getOrCreateDeviceId())
  const isAuthenticated = ref(false)
  const isLoading = ref(false)
  const oidcEnabled = ref(false)
  const localAuthEnabled = ref(true)
  const initialized = ref(false)
  const refreshPromise = ref(null) // Prevent concurrent refresh requests
  const initPromise = ref(null) // Prevent concurrent initialization
  const logoutPromise = ref(null) // Prevent concurrent logout requests

  // Getters
  const isLoggedIn = computed(() => isAuthenticated.value && !!user.value)
  const isSuperuser = computed(() => user.value?.is_superuser || false)
  const isAdmin = computed(() => user.value?.is_superuser || false)
  const userDisplayName = computed(() => {
    if (!user.value) return ''
    return (
      `${user.value.first_name} ${user.value.last_name}`.trim() ||
      user.value.preferred_username ||
      user.value.email
    )
  })

  // Language settings getters
  const uiLanguage = computed(() => user.value?.ui_language || 'en-US')
  const audioLanguages = computed(() => user.value?.audio_languages || ['en'])
  const subtitleLanguage = computed(() => user.value?.subtitle_language || null)

  // Actions
  function loadTokensFromStorage() {
    const storedAccessToken = getAccessToken()
    const storedRefreshToken = getRefreshToken()

    if (storedAccessToken && storedRefreshToken) {
      accessToken.value = storedAccessToken
      refreshToken.value = storedRefreshToken
      setAuthHeader(storedAccessToken)
    }
  }

  function saveTokensToStorage(newAccessToken, newRefreshToken) {
    saveAuthTokens(newAccessToken, newRefreshToken)
    accessToken.value = newAccessToken
    refreshToken.value = newRefreshToken
    setAuthHeader(newAccessToken)
  }

  function clearTokensFromStorage() {
    clearAuthTokens()
    accessToken.value = null
    refreshToken.value = null
    removeAuthHeader()
  }

  function setAuthHeader(token) {
    if (token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`
    }
  }

  function removeAuthHeader() {
    delete api.defaults.headers.common['Authorization']
  }

  async function fetchAuthStatus() {
    try {
      isLoading.value = true
      const response = await api.get('/api/auth/status')

      isAuthenticated.value = response.data.authenticated
      user.value = response.data.user
      oidcEnabled.value = response.data.oidc_enabled === true
      localAuthEnabled.value =
        response.data.local_auth_enabled ??
        response.data.auth_methods?.includes('local') ??
        true

      return response.data
    } catch (error) {
      logger.error('Failed to fetch auth status:', error)
      // Don't throw error to prevent blocking app initialization
      isAuthenticated.value = false
      user.value = null
      oidcEnabled.value = false
      localAuthEnabled.value = true
      return { authenticated: false, user: null, oidc_enabled: false, local_auth_enabled: true }
    } finally {
      isLoading.value = false
    }
  }

  async function fetchUserInfo() {
    try {
      const response = await api.get('/api/auth/me')
      user.value = response.data
      isAuthenticated.value = true
      syncCodecSettings().catch((err) => logger.warn('Codec sync failed (non-fatal):', err))
      return response.data
    } catch (error) {
      logger.error('Failed to fetch user info:', error)
      logout()
      throw error
    }
  }

  async function login(returnTo = null) {
    if (!oidcEnabled.value) {
      throw new Error('OIDC authentication is not enabled')
    }

    const baseUrl = getServerUrl().replace(/\/+$/, '')
    const loginUrl = new URL(`${baseUrl || window.location.origin}/api/auth/login`)
    const target = sanitizeRedirect(returnTo || `${window.location.pathname}${window.location.search}`)
    if (target !== '/auth/login') {
      loginUrl.searchParams.set('return_to', target)
    }
    window.location.href = baseUrl ? loginUrl.toString() : `${loginUrl.pathname}${loginUrl.search}`
  }

  async function localLogin(email, password) {
    try {
      isLoading.value = true
      const deviceInfo = getDeviceInfo()
      const response = await api.post('/api/auth/local/login', {
        email,
        password,
        device_id: deviceInfo.device_id,
        device_info: deviceInfo,
      })

      const { access_token, refresh_token } = response.data
      saveTokensToStorage(access_token, refresh_token)
      isAuthenticated.value = true

      // Benutzerinformationen laden
      await fetchUserInfo()

      return response.data
    } catch (error) {
      logger.error('Local login failed:', error)
      throw error
    } finally {
      isLoading.value = false
    }
  }

  function handleLoginCallback() {
    const urlParams = new URLSearchParams(window.location.search)
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const urlAccessToken = hashParams.get('access_token') || urlParams.get('access_token')
    const urlRefreshToken = hashParams.get('refresh_token') || urlParams.get('refresh_token')

    if (urlAccessToken && urlRefreshToken) {
      saveTokensToStorage(urlAccessToken, urlRefreshToken)
      isAuthenticated.value = true

      // URL bereinigen
      window.history.replaceState({}, document.title, window.location.pathname)

      // Benutzerinformationen laden
      return fetchUserInfo()
    } else {
      throw new Error('No tokens found in callback URL')
    }
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) {
      throw new Error('No refresh token available')
    }

    // Return existing promise if refresh is already in progress
    if (refreshPromise.value) {
      return refreshPromise.value
    }

    refreshPromise.value = _performTokenRefresh()

    try {
      const result = await refreshPromise.value
      return result
    } finally {
      refreshPromise.value = null
    }
  }

  async function _performTokenRefresh() {
    try {
      const response = await api.post(
        '/api/auth/refresh',
        {},
        {
          headers: {
            Authorization: `Bearer ${refreshToken.value}`,
          },
        },
      )

      const { access_token, refresh_token } = response.data
      saveTokensToStorage(access_token, refresh_token)

      return response.data
    } catch (error) {
      logger.error('Failed to refresh token:', error)
      clearAuthState()
      throw error
    }
  }

  function clearAuthState() {
    clearTokensFromStorage()
    user.value = null
    isAuthenticated.value = false
  }

  async function logout() {
    // Return existing promise if logout is already in progress
    if (logoutPromise.value) {
      return logoutPromise.value
    }

    logoutPromise.value = _performLogout()

    try {
      return await logoutPromise.value
    } finally {
      logoutPromise.value = null
    }
  }

  async function _performLogout() {
    try {
      if (isAuthenticated.value) {
        const response = await api.post('/api/auth/logout')

        // Falls OIDC Logout URL zurückgegeben wird
        if (response.data.logout_url) {
          clearAuthState()
          // Validate redirect URL — only allow same-origin or relative paths
          const logoutUrl = response.data.logout_url
          if (logoutUrl.startsWith('/') || logoutUrl.startsWith(window.location.origin)) {
            window.location.href = logoutUrl
          }
          return
        }
      }
    } catch (error) {
      logger.error('Logout error:', error)
    }

    // Lokaler Logout
    clearAuthState()
  }

  async function initialize() {
    if (initialized.value) {
      return
    }

    // Return existing promise if initialization is already in progress
    if (initPromise.value) {
      return initPromise.value
    }

    initPromise.value = _performInitialization()

    try {
      const result = await initPromise.value
      return result
    } finally {
      initPromise.value = null
    }
  }

  async function _performInitialization() {
    try {
      // Token aus localStorage laden
      loadTokensFromStorage()

      // Auth-Status prüfen
      await fetchAuthStatus()

      // Falls Token vorhanden aber nicht authentifiziert, versuche Refresh
      if (accessToken.value && !isAuthenticated.value) {
        try {
          await refreshAccessToken()
          await fetchAuthStatus()
        } catch (refreshError) {
          logger.error('Token refresh failed during initialization:', refreshError)
          clearTokensFromStorage()
        }
      }
    } catch (error) {
      logger.error('Auth initialization failed:', error)
      clearTokensFromStorage()
    } finally {
      initialized.value = true
    }
  }

  function detectSupportedVideoCodecs() {
    const video = document.createElement('video')
    const codecs = []
    // H.264 / AVC
    if (video.canPlayType('video/mp4; codecs="avc1.42E01E"')) codecs.push('h264')
    // H.265 / HEVC
    if (
      video.canPlayType('video/mp4; codecs="hev1.1.6.L93.90"') ||
      video.canPlayType('video/mp4; codecs="hvc1.1.6.L93.90"')
    )
      codecs.push('hevc')
    // AV1
    if (
      video.canPlayType('video/mp4; codecs="av01.0.04M.08"') ||
      video.canPlayType('video/webm; codecs="av01"')
    )
      codecs.push('av1')
    // VP9
    if (video.canPlayType('video/webm; codecs="vp9"')) codecs.push('vp9')
    // VP8
    if (video.canPlayType('video/webm; codecs="vp8"')) codecs.push('vp8')
    return codecs
  }

  function detectSupportedAudioCodecs() {
    const video = document.createElement('video')
    const codecs = []
    // AAC
    if (video.canPlayType('audio/mp4; codecs="mp4a.40.2"')) codecs.push('aac')
    // MP3
    if (video.canPlayType('audio/mpeg')) codecs.push('mp3')
    // Opus
    if (
      video.canPlayType('audio/ogg; codecs="opus"') ||
      video.canPlayType('audio/webm; codecs="opus"')
    )
      codecs.push('opus')
    // Vorbis
    if (video.canPlayType('audio/ogg; codecs="vorbis"')) codecs.push('vorbis')
    // AC-3 (Dolby Digital)
    if (video.canPlayType('audio/ac3') || video.canPlayType('audio/mp4; codecs="ac-3"'))
      codecs.push('ac3')
    // E-AC-3 (Dolby Digital Plus)
    if (video.canPlayType('audio/eac3') || video.canPlayType('audio/mp4; codecs="ec-3"'))
      codecs.push('eac3')
    // FLAC
    if (video.canPlayType('audio/flac')) codecs.push('flac')
    return codecs
  }

  async function syncCodecSettings() {
    try {
      const supportedVideoCodecs = detectSupportedVideoCodecs()
      const supportedAudioCodecs = detectSupportedAudioCodecs()

      // Fetch current settings to preserve existing bonus/penalty values
      const currentRes = await api.get('/api/users/me/codec-settings')
      const current = currentRes.data

      await api.put('/api/users/me/codec-settings', {
        supported_video_codecs: supportedVideoCodecs,
        supported_audio_codecs: supportedAudioCodecs,
        // Keep existing bonus/penalty or fall back to sensible defaults
        codec_match_bonus: current.codec_match_bonus || 5,
        codec_mismatch_penalty: current.codec_mismatch_penalty || 10,
      })
    } catch (error) {
      // Non-critical — don't block login on failure
      logger.warn('Failed to sync codec settings:', error)
    }
  }

  async function updateLanguageSettings(settings) {
    try {
      const response = await api.put('/api/users/me/language-settings', settings)
      // Update user object with new language settings
      if (user.value) {
        user.value = {
          ...user.value,
          ui_language: response.data.ui_language,
          audio_languages: response.data.audio_languages,
          subtitle_language: response.data.subtitle_language,
        }
      }
      return response.data
    } catch (error) {
      logger.error('Failed to update language settings:', error)
      throw error
    }
  }

  async function fetchLanguageSettings() {
    try {
      const response = await api.get('/api/users/me/language-settings')
      return response.data
    } catch (error) {
      logger.error('Failed to fetch language settings:', error)
      throw error
    }
  }

  async function fetchPlaybackPreferences() {
    try {
      const response = await api.get('/api/users/me/playback-preferences')
      return response.data
    } catch (error) {
      logger.error('Failed to fetch playback preferences:', error)
      throw error
    }
  }

  async function updatePlaybackPreferences(prefs) {
    try {
      const response = await api.put('/api/users/me/playback-preferences', prefs)
      return response.data
    } catch (error) {
      logger.error('Failed to update playback preferences:', error)
      throw error
    }
  }

  async function fetchGamingPreferences() {
    try {
      const response = await api.get('/api/users/me/gaming-preferences')
      return response.data
    } catch (error) {
      logger.error('Failed to fetch gaming preferences:', error)
      throw error
    }
  }

  async function updateGamingPreferences(prefs) {
    try {
      const response = await api.put('/api/users/me/gaming-preferences', prefs)
      return response.data
    } catch (error) {
      logger.error('Failed to update gaming preferences:', error)
      throw error
    }
  }

  return {
    // State
    user,
    accessToken,
    refreshToken,
    deviceId,
    isAuthenticated,
    isLoading,
    oidcEnabled,
    localAuthEnabled,
    initialized,
    refreshPromise,
    initPromise,

    // Getters
    isLoggedIn,
    isSuperuser,
    isAdmin,
    userDisplayName,
    uiLanguage,
    audioLanguages,
    subtitleLanguage,

    // Actions
    loadTokensFromStorage,
    saveTokensToStorage,
    clearTokensFromStorage,
    setAuthHeader,
    removeAuthHeader,
    fetchAuthStatus,
    fetchUserInfo,
    login,
    localLogin,
    handleLoginCallback,
    refreshAccessToken,
    logout,
    initialize,
    updateLanguageSettings,
    fetchLanguageSettings,
    fetchPlaybackPreferences,
    updatePlaybackPreferences,
    fetchGamingPreferences,
    updateGamingPreferences,
    syncCodecSettings,
    detectSupportedVideoCodecs,
    detectSupportedAudioCodecs,
    getDeviceInfo,
  }
})
