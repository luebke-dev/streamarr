/**
 * Remote Control Boot File
 *
 * Handles incoming remote control commands globally.
 * When a play command is received from another device,
 * it navigates to the PlayPage to start playback.
 */

import { boot } from 'quasar/wrappers'
import { useWebSocket } from 'src/composables/useWebSocket'
import { useRemoteControlStore } from 'stores/remoteControl'
import { logger } from 'src/utils/logger'

let unsubscribe = null

export default boot(({ router }) => {
  // Clean up any previous handler (hot reload safety)
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }

  const ws = useWebSocket()
  const remoteControlStore = useRemoteControlStore()

  unsubscribe = ws.on('remote_control', (data) => {
    const { command, payload, from_device_id } = data
    logger.debug('[RemoteControl Boot] Command received:', command, payload)

    if (command === 'play' && payload) {
      const { media_type, media_guid } = payload

      if (media_guid) {
        remoteControlStore.isRemoteControlled = true
        remoteControlStore.remoteController = from_device_id

        router.push({
          path: `/play/${media_guid}`,
          query: { type: media_type || 'movie' },
        })
      }
    }
  })

  logger.debug('[RemoteControl] Global handler registered')
})
