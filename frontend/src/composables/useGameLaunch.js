import { ref } from 'vue'
import { launchGameSession, getGamePlatforms } from 'src/services/lightraysService'
import { logger } from 'src/utils/logger'
import { useNativeGameStream, usesNativeGameStream } from 'src/composables/useNativeGameStream'

export function useGameLaunch({ uuid, status, loading, errorMessage, t }) {
  const gameSessionId = ref('')
  const wsTicket = ref('')
  const websocketUrl = ref('')
  const gameIceServers = ref([])
  // Platforms the game can be played on (N64, PC, …) for the version picker.
  const gamePlatforms = ref([])
  const selectedPlatform = ref(null)

  // The desktop plays games through the shell, not through a `<video>` element:
  // the plan's architecture rule is that every video output is native, and the
  // webview is UI chrome (ADR 001). The two paths share the platform picker and
  // the status handling; only the player differs.
  const native = useNativeGameStream({
    onEnded: (phase) => {
      // The shell's session ended, so this is not an error. `goBack` is the
      // caller's, through the same `disconnected` route the web path uses.
      status.value = phase === 'failed' ? 'error' : 'idle'
      if (phase === 'failed') {
        errorMessage.value = t('playPage.failedToStartGame')
      }
    },
  })

  async function fetchGamePlatforms() {
    try {
      gamePlatforms.value = await getGamePlatforms(uuid.value)
    } catch (error) {
      logger.warn('Failed to load game platforms', error)
      gamePlatforms.value = []
    }
    return gamePlatforms.value
  }

  async function launchGameStream(platform = null) {
    selectedPlatform.value = platform
    if (usesNativeGameStream()) {
      return launchNativeGameStream(platform)
    }
    try {
      loading.value = true
      const dpr = window.devicePixelRatio || 1
      const header = document.querySelector('.q-header')
      const headerH = header ? header.offsetHeight : 0
      const rawWidth = Math.round(window.innerWidth * dpr)
      const rawHeight = Math.round((window.innerHeight - headerH) * dpr)
      const evenWidth = rawWidth % 2 === 0 ? rawWidth : rawWidth + 1
      const evenHeight = rawHeight % 2 === 0 ? rawHeight : rawHeight + 1
      const width = Math.max(64, Math.min(7680, evenWidth))
      const height = Math.max(64, Math.min(4320, evenHeight))

      const data = await launchGameSession(uuid.value, { width, height, platform })

      gameSessionId.value = data.session_id
      wsTicket.value = data.ws_ticket || ''
      websocketUrl.value = data.websocket_url || ''
      gameIceServers.value = data.ice_servers || []
      status.value = 'game-streaming'
      loading.value = false
    } catch (error) {
      // 409 = the ROM for the chosen platform isn't downloaded yet; the backend
      // has kicked off the acquisition. Reuse the SAME download-waiting screen
      // as movies/episodes — the caller starts the shared download polling,
      // which relaunches the game (onAvailable) once the ROM is on disk.
      if (error.response?.status === 409) {
        status.value = 'downloading'
        errorMessage.value = ''
        loading.value = false
        return
      }
      logger.error('Failed to start game streaming session', error)
      status.value = 'error'
      errorMessage.value = error.response?.data?.detail || t('playPage.failedToStartGame')
      loading.value = false
    }
  }

  /**
   * Starts the game stream in the shell.
   *
   * Returns the same way the web path does — a session object, or `null` after
   * setting `status`/`errorMessage` — so the caller needs no branch. The
   * difference is where the picture comes from, and that is the whole point.
   */
  async function launchNativeGameStream(platform) {
    loading.value = true
    const result = await native.start(uuid.value, platform)
    loading.value = false
    if (result?.running) {
      status.value = 'native-game-streaming'
      return result
    }

    // 409 is not a failure: the server has started fetching the ROM and the
    // caller's download polling relaunches the game when it lands. The shell
    // carries the *status code* for exactly this reason — matching on the
    // message text would break the moment the wording changed.
    const outcomeStatus = result?.errorStatus
    if (outcomeStatus === 409) {
      status.value = 'downloading'
      errorMessage.value = ''
      return null
    }
    status.value = 'error'
    errorMessage.value = result?.error || t('playPage.failedToStartGame')
    return null
  }

  /** Asks the server to rebuild its pipeline at the current window size. */
  async function matchResolution() {
    return native.matchResolution()
  }

  /** Ends the native stream and tells the server. */
  async function stopNativeGameStream() {
    return native.stop()
  }

  /** A live statistics reading for the debug panel. */
  async function fetchGameStats() {
    return native.fetchStats()
  }

  return {
    gameSessionId,
    wsTicket,
    websocketUrl,
    gameIceServers,
    gamePlatforms,
    selectedPlatform,
    fetchGamePlatforms,
    launchGameStream,
    // The native path's state and controls, so the view can render the same
    // toolbar whether the picture comes from a `<video>` or from the shell.
    nativeGame: native.state,
    matchResolution,
    stopNativeGameStream,
    fetchGameStats,
  }
}
