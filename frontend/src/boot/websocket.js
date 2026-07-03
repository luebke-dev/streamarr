/**
 * Global WebSocket boot file.
 *
 * Initializes a persistent WebSocket connection that stays active
 * across the entire application. Automatically connects when the user
 * logs in and disconnects on logout.
 */

import { defineBoot } from '#q-app/wrappers'
import { watch } from 'vue'
import { useAuthStore } from 'src/stores/auth'
import { useWebSocket } from 'src/composables/useWebSocket'
import { logger } from 'src/utils/logger'

export default defineBoot(({ app }) => {
  const authStore = useAuthStore()
  const { connect, disconnect, isConnected } = useWebSocket()

  // Watch for authentication changes
  watch(
    () => authStore.isAuthenticated,
    (isAuthenticated) => {
      if (isAuthenticated) {
        logger.debug('[WebSocket Boot] User authenticated, connecting...')
        connect()
      } else {
        logger.debug('[WebSocket Boot] User logged out, disconnecting...')
        disconnect()
      }
    },
    { immediate: true },
  )

  // Reconnect after a token refresh. Watching the reactive store ref instead
  // of polling localStorage means this fires exactly once per rotation.
  watch(
    () => authStore.accessToken,
    (newToken, oldToken) => {
      if (newToken && newToken !== oldToken && authStore.isAuthenticated) {
        logger.debug('[WebSocket Boot] Token changed, reconnecting...')
        disconnect({ clearHandlers: false })
        setTimeout(() => {
          connect()
        }, 100)
      }
    },
  )

  // Make WebSocket available globally via app.config for debugging
  app.config.globalProperties.$websocket = {
    connect,
    disconnect,
    get isConnected() {
      return isConnected.value
    },
  }

  logger.debug('[WebSocket Boot] WebSocket boot initialized')
})
