/**
 * Remote-control receiver composable for the play page.
 *
 * Wraps the WebSocket subscription to 'remote_control' commands sent
 * by another device (the remote / cast client). Translates incoming
 * commands into Video.js player calls, episode navigation, or a
 * router navigation for play_media. Auto-unsubscribes on page unmount
 * and resets the global isRemoteControlled flag.
 *
 * Inputs:
 *   - wsStore: from useWebSocket() — exposes .on / .off
 *   - videoJsPlayer: ref to the Video.js player
 *   - router: vue-router instance (for play_media navigation)
 *   - remoteControlStore: pinia store with isRemoteControlled,
 *       remoteController, clearRemoteControlled()
 *   - transcodeStartPosition: ref<number> — offset of the current transcode
 *   - onSeek(position): seek handler (3-tier seek logic) for absolute positions
 *   - playNextEpisode / playPreviousEpisode: composable actions
 *
 * Returns:
 *   - subscribe(): start listening; called from PlayPage once the
 *       player setup is done
 *   - unsubscribe(): stop listening early (also runs on unmount)
 *
 * The 'stop' command navigates back via router.back().
 */

import { onBeforeUnmount } from 'vue'
import { logger } from 'src/utils/logger'

export function useRemoteControlReceiver({
  wsStore,
  videoJsPlayer,
  router,
  remoteControlStore,
  transcodeStartPosition,
  onSeek,
  playNextEpisode,
  playPreviousEpisode,
}) {
  let active = false

  const getPlayer = () => {
    const player = videoJsPlayer.value
    return player && !player.isDisposed?.() ? player : null
  }

  const realPlayerTime = (player) =>
    (transcodeStartPosition?.value || 0) + (player.currentTime() || 0)

  const handleRemoteControlCommand = (data) => {
    const { command, payload } = data
    logger.debug('[useRemoteControlReceiver] command received:', command, payload)

    switch (command) {
      case 'pause':
        getPlayer()?.pause()
        break
      case 'resume':
      case 'play':
        getPlayer()?.play()
        break
      case 'stop':
        router.back()
        break
      case 'seek':
        if (getPlayer() && payload?.position !== undefined) {
          onSeek(payload.position)
        }
        break
      case 'volume':
        if (payload?.level !== undefined) {
          getPlayer()?.volume(payload.level)
        }
        break
      case 'mute': {
        const player = getPlayer()
        if (player) {
          player.muted(!player.muted())
        }
        break
      }
      case 'next':
        playNextEpisode()
        break
      case 'previous':
        playPreviousEpisode()
        break
      case 'skip_forward': {
        const player = getPlayer()
        if (player) {
          onSeek(realPlayerTime(player) + (payload?.seconds || 10))
        }
        break
      }
      case 'skip_backward': {
        const player = getPlayer()
        if (player) {
          onSeek(Math.max(0, realPlayerTime(player) - (payload?.seconds || 10)))
        }
        break
      }
      case 'play_media':
        if (payload?.media_guid) {
          router.replace({
            path: `/play/${payload.media_guid}`,
            query: payload.media_type ? { type: payload.media_type } : {},
          })
        }
        break
      case 'play_command': {
        const itemIds = Array.isArray(payload?.item_ids) ? payload.item_ids : []
        const startIndex = Number.isInteger(payload?.start_index) ? payload.start_index : 0
        const targetItemId = itemIds[startIndex] || itemIds[0]
        if (targetItemId) {
          const query = {
            play_command: payload.play_command || 'play_now',
          }
          if (payload.media_source_id) query.media_source_id = payload.media_source_id
          if (payload.start_position_seconds !== undefined) {
            query.t = String(payload.start_position_seconds)
          }
          if (payload.audio_stream_index !== undefined) {
            query.audio_stream_index = String(payload.audio_stream_index)
          }
          if (payload.subtitle_stream_index !== undefined) {
            query.subtitle_stream_index = String(payload.subtitle_stream_index)
          }
          router.replace({ path: `/play/${targetItemId}`, query })
        }
        break
      }
    }

    // Mark that we're being controlled remotely
    remoteControlStore.isRemoteControlled = true
    remoteControlStore.remoteController = data.from_device_id
  }

  const subscribe = () => {
    if (active) return
    wsStore.on('remote_control', handleRemoteControlCommand)
    active = true
  }

  const unsubscribe = () => {
    if (!active) return
    wsStore.off('remote_control', handleRemoteControlCommand)
    active = false
  }

  onBeforeUnmount(() => {
    unsubscribe()
    remoteControlStore.clearRemoteControlled()
  })

  return { subscribe, unsubscribe }
}
