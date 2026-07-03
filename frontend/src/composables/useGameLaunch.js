import { ref } from 'vue'
import { launchGameSession } from 'src/services/lightraysService'
import { logger } from 'src/utils/logger'

export function useGameLaunch({ uuid, status, loading, errorMessage, t }) {
  const gameSessionId = ref('')
  const wsTicket = ref('')
  const websocketUrl = ref('')
  const gameIceServers = ref([])

  async function launchGameStream() {
    try {
      const dpr = window.devicePixelRatio || 1
      const header = document.querySelector('.q-header')
      const headerH = header ? header.offsetHeight : 0
      const rawWidth = Math.round(window.innerWidth * dpr)
      const rawHeight = Math.round((window.innerHeight - headerH) * dpr)
      const evenWidth = rawWidth % 2 === 0 ? rawWidth : rawWidth + 1
      const evenHeight = rawHeight % 2 === 0 ? rawHeight : rawHeight + 1
      const width = Math.max(64, Math.min(7680, evenWidth))
      const height = Math.max(64, Math.min(4320, evenHeight))

      const data = await launchGameSession(uuid.value, { width, height })

      gameSessionId.value = data.session_id
      wsTicket.value = data.ws_ticket || ''
      websocketUrl.value = data.websocket_url || ''
      gameIceServers.value = data.ice_servers || []
      status.value = 'game-streaming'
      loading.value = false
    } catch (error) {
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
    launchGameStream,
  }
}
