/**
 * Watch Party synchronisation composable for the play page.
 *
 * Encapsulates the logic that keeps a Video.js player in sync with the
 * Watch Party state pushed via WebSocket:
 *   - Late-joiner: request current state from host on player ready
 *   - Resume: apply party position instead of viewing history
 *   - Push play / pause / seek state to the party (called from
 *     existing player-event handlers in PlayPage so they can keep
 *     their other side effects)
 *   - Watch on partyStore.syncState applies host state to local player
 *     (with ignoringSync guard to prevent feedback loops)
 *   - Host: every 10 s, push current state so DB stays fresh and late
 *     joiners get accurate position
 *   - Host: PATCH party media when navigating to a new PlayPage
 *   - Host: respond to sync requests with current player state
 *
 * Inputs:
 *   - partyStore: pinia store with isInParty, isHost, activeParty,
 *       syncState
 *   - partyWs: from usePartyWebSocket() — exposes initialize,
 *       syncPlayback, requestSync, onSyncRequested
 *   - videoJsPlayer: ref to the Video.js player (used by host poller +
 *       host onSyncRequested handler)
 *   - uuid: ref<string> — current media uuid
 *   - contentType: ref<string> — 'movie' / 'episode' / etc.
 *   - transcodeStartPosition: ref<number> — offset of the current transcode
 *   - onSeek(position): seek handler used to apply inbound sync positions
 *
 * Returns:
 *   - applyResumePosition(lastPositionRef) → boolean
 *       writes the party position into lastPositionRef and returns true
 *       when the party has a non-zero current_time; otherwise returns
 *       false so the caller can fall back to viewing history.
 *   - initialize() — call from onMounted: starts the WS connection,
 *       PATCHes party media when host navigates, registers the
 *       onSyncRequested host handler.
 *   - attachToPlayer(vjsPlayer) — call from onPlayerMounted with the
 *       local player handle: starts the host poller and registers the
 *       partyStore.syncState watcher.
 *   - pushPlayerState(vjsPlayer, isPlaying) — call from PlayPage
 *       play/pause/seeked event handlers; no-op when not in a party
 *       or while applying an inbound sync.
 *   - requestLateJoinerSync() — call from onPlayerReady.
 */

import { watch, onUnmounted } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import { useInterval } from 'src/composables/useInterval'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'
import { realPlayerTime as computeRealPlayerTime } from 'src/composables/playbackPosition'

const SYNC_TOLERANCE = 2.0
const HOST_SYNC_INTERVAL_MS = 10000
const LATE_JOINER_SYNC_DELAY_MS = 1000
const IGNORE_SYNC_RESET_MS = 500

export function usePartySync({
  partyStore,
  partyWs,
  videoJsPlayer,
  uuid,
  contentType,
  transcodeStartPosition,
  onSeek,
}) {
  let ignoringSync = false
  let hostTick = null
  let stopSyncWatcher = null
  const hostPoller = useInterval(() => hostTick?.(), HOST_SYNC_INTERVAL_MS)
  const syncTimers = useTimeoutRegistry()

  const realPlayerTime = (vjsPlayer) =>
    computeRealPlayerTime(vjsPlayer, transcodeStartPosition)

  const applyResumePosition = (lastPositionRef) => {
    if (partyStore.isInParty && partyStore.activeParty?.current_time > 0) {
      lastPositionRef.value =
        partyStore.activeParty.adjusted_current_time ?? partyStore.activeParty.current_time
      return true
    }
    return false
  }

  const initialize = () => {
    partyWs.initialize()

    // Host: update party media when navigating to a new PlayPage
    if (partyStore.isInParty && partyStore.isHost && uuid.value) {
      const currentMediaId = partyStore.activeParty?.media_id
      if (currentMediaId !== uuid.value) {
        api
          .patch(`/api/parties/${partyStore.activeParty.guid}`, {
            media_id: uuid.value,
            media_type: contentType.value,
          })
          .catch((e) => logger.warn('Failed to update party media:', e))
      }
    }

    // When host receives a sync request from a late joiner, send current player state
    partyWs.onSyncRequested(() => {
      if (videoJsPlayer.value) {
        partyWs.syncPlayback(
          realPlayerTime(videoJsPlayer.value),
          !videoJsPlayer.value.paused(),
          videoJsPlayer.value.playbackRate(),
        )
      }
    })
  }

  const pushPlayerState = (vjsPlayer, isPlaying) => {
    if (!partyStore.isInParty || ignoringSync || !vjsPlayer) return
    partyWs.syncPlayback(realPlayerTime(vjsPlayer), isPlaying, vjsPlayer.playbackRate())
  }

  const attachToPlayer = (vjsPlayer) => {
    // Host periodically sends player state so DB stays fresh and late joiners get accurate position
    if (partyStore.isInParty && partyStore.isHost) {
      hostTick = () => {
        const p = videoJsPlayer.value
        if (p && !p.paused() && partyStore.isInParty) {
          partyWs.syncPlayback(realPlayerTime(p), true, p.playbackRate())
        }
      }
      hostPoller.start()
    }

    if (stopSyncWatcher) {
      stopSyncWatcher()
    }

    // Watch Party: sync state is replaced on each update, so a shallow watch
    // fires once per update without paying the deep-compare cost.
    stopSyncWatcher = watch(
      () => partyStore.syncState,
      (newSyncState) => {
        if (!partyStore.isInParty || !vjsPlayer) return

        ignoringSync = true

        const currentTime = realPlayerTime(vjsPlayer)
        const timeDiff = Math.abs(currentTime - newSyncState.currentTime)

        if (timeDiff > SYNC_TOLERANCE) {
          if (onSeek) {
            onSeek(newSyncState.currentTime)
          } else {
            vjsPlayer.currentTime(newSyncState.currentTime)
          }
        }

        if (newSyncState.isPlaying && vjsPlayer.paused()) {
          vjsPlayer.play().catch((e) => logger.debug('Autoplay prevented:', e.message))
        } else if (!newSyncState.isPlaying && !vjsPlayer.paused()) {
          vjsPlayer.pause()
        }

        if (newSyncState.playbackRate && vjsPlayer.playbackRate() !== newSyncState.playbackRate) {
          vjsPlayer.playbackRate(newSyncState.playbackRate)
        }

        syncTimers.schedule(() => {
          ignoringSync = false
        }, IGNORE_SYNC_RESET_MS)
      },
    )
  }

  const requestLateJoinerSync = () => {
    if (partyStore.isInParty && !partyStore.isHost) {
      syncTimers.schedule(() => {
        partyWs.requestSync()
      }, LATE_JOINER_SYNC_DELAY_MS)
    }
  }

  onUnmounted(() => {
    if (stopSyncWatcher) {
      stopSyncWatcher()
      stopSyncWatcher = null
    }
  })

  return {
    applyResumePosition,
    initialize,
    attachToPlayer,
    pushPlayerState,
    requestLateJoinerSync,
  }
}
