import { ref } from 'vue'
import { launchGameSession, getGamePlatforms } from 'src/services/lightraysService'
import { logger } from 'src/utils/logger'

export function useGameLaunch({ uuid, status, loading, errorMessage, t }) {
  const gameSessionId = ref('')
  const wsTicket = ref('')
  const websocketUrl = ref('')
  const gameIceServers = ref([])
  // Platforms the game can be played on (N64, PC, …) for the version picker.
  const gamePlatforms = ref([])
  const selectedPlatform = ref(null)

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
    try {
      selectedPlatform.value = platform
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

  return {
    gameSessionId,
    wsTicket,
    websocketUrl,
    gameIceServers,
    gamePlatforms,
    selectedPlatform,
    fetchGamePlatforms,
    launchGameStream,
  }
}
