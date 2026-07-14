import { ref, onUnmounted, watch } from 'vue'
import { getTrickplayManifest } from 'src/composables/usePlay'
import { logger } from 'src/utils/logger'

/**
 * Bundles the @mounted / @ready / @timeupdate / @ended / @pause handlers
 * for the Video.js player. Encapsulates the wiring between vjsPlayer
 * events and the surrounding app state (websocket status broadcast,
 * watch-party sync, viewing-history updates, sprite-thumbnails setup,
 * resume-position restore, episode auto-advance).
 *
 * Args (all reactive refs unless noted):
 *   - videoJsPlayer, playerState, videoElement
 *   - playToken, sessionId
 *   - streamPosition, transcodeStartPosition, bufferedAmount, isPlaying
 *   - duration, videoDuration, lastPosition
 *   - contentInfo, contentType, uuid
 *   - wsStore                    websocket store (for updatePlaybackStatus)
 *   - partySync                  watch-party sync helper
 *   - setupXhrAuth(label)        re-attach VHS auth header (post-mount/ready)
 *   - updateProgress(t, dur)     persist viewing progress
 *   - reportPlaybackStarted(t, dur) report native playstate start
 *   - onPlayerError(error)       notify consumer of a fatal player error
 *   - setupMediaSession()        wire MediaSession metadata + handlers
 *   - checkEpisodeNavigation()   refresh prev/next episode state
 *   - shouldAutoAdvanceOnEnded() whether ended should advance playback
 *   - playNextEpisode()          auto-advance on @ended
 *
 * Returns: { onPlayerMounted, onPlayerReady, onTimeUpdate, onVideoEnded,
 *            onVideoPause }
 */
export function useVideoPlayerEvents({
  videoJsPlayer,
  playerState,
  videoElement,
  playToken,
  sessionId,
  streamPosition,
  transcodeStartPosition,
  bufferedAmount,
  isPlaying,
  duration,
  videoDuration,
  lastPosition,
  contentInfo,
  contentType,
  uuid,
  wsStore,
  partySync,
  setupXhrAuth,
  updateProgress,
  reportPlaybackStarted,
  onPlayerError,
  setupMediaSession,
  checkEpisodeNavigation,
  shouldAutoAdvanceOnEnded,
  playNextEpisode,
}) {
  // Trickplay manifest for the seek-bar preview. Rendered by our own controls
  // (the player runs with `controls: false`), so it is exposed as state rather
  // than fed to a video.js plugin.
  const trickplayManifest = ref(null)
  const TRICKPLAY_POLL_INTERVAL_MS = 5000
  // Generation runs at roughly 30-60x realtime, so a feature-length film needs
  // a few minutes' worth of polling before its last sheet lands.
  const TRICKPLAY_MAX_ATTEMPTS = 120 // ~10 minutes, then stop asking
  let trickplayTimer = null

  function cancelTrickplayPolling() {
    if (trickplayTimer) {
      clearTimeout(trickplayTimer)
      trickplayTimer = null
    }
  }

  /** Seconds of the timeline the manifest's sprite sheets actually cover. */
  function coveredSeconds(manifest) {
    const sheets = manifest.sprites || []
    if (!sheets.length) return 0
    const perSheet = (manifest.columns || 10) * (manifest.rows || 10)
    const last = sheets[sheets.length - 1]
    return last.end_seconds ?? sheets.length * perSheet * (manifest.interval_seconds || 10)
  }

  async function setupTrickplaySprites(attempt = 0) {
    cancelTrickplayPolling()
    if (!sessionId.value || !playToken.value) return

    const forSession = sessionId.value
    const pollAgain = (nextAttempt) => {
      if (nextAttempt <= TRICKPLAY_MAX_ATTEMPTS) {
        trickplayTimer = setTimeout(
          () => setupTrickplaySprites(nextAttempt),
          TRICKPLAY_POLL_INTERVAL_MS,
        )
      } else {
        logger.debug('Stopped polling for trickplay sprites.')
      }
    }

    try {
      const manifest = await getTrickplayManifest(forSession, playToken.value)
      // The session may have been swapped while the request was in flight.
      if (sessionId.value !== forSession) return

      if (!manifest.ready || !manifest.sprites?.length) {
        // The sprites are rendered by a sibling container that starts together
        // with playback, so the first manifest is normally still empty. Without
        // this retry we would ask exactly once — at the one moment the answer is
        // guaranteed to be "not yet" — and never show a thumbnail.
        pollAgain(attempt + 1)
        return
      }

      // Show what exists already, but keep polling: FFmpeg writes one sheet per
      // 100 frames, so an early manifest covers only the start of the timeline
      // and the tail of the seek bar would stay blank forever.
      trickplayManifest.value = manifest

      const runtime = videoDuration.value || duration.value || 0
      if (runtime && coveredSeconds(manifest) < runtime) {
        pollAgain(attempt + 1)
      }
    } catch (error) {
      logger.debug('Failed to load the trickplay manifest:', error)
    }
  }

  function onPlayerMounted({ video, player: vjsPlayer, state }) {
    videoJsPlayer.value = vjsPlayer
    playerState.value = state
    videoElement.value = video

    if (playToken.value) {
      setupXhrAuth('Mount')
    }

    setupTrickplaySprites()

    // Wire Watch Party host poller + inbound sync watcher
    partySync.attachToPlayer(vjsPlayer)

    vjsPlayer.on('play', () => {
      isPlaying.value = true
      partySync.pushPlayerState(vjsPlayer, true)
    })

    vjsPlayer.on('pause', () => {
      isPlaying.value = false
      updateProgress(state.currentTime || 0, state.duration || videoDuration.value, {
        isPaused: true,
      })
      partySync.pushPlayerState(vjsPlayer, false)
    })

    vjsPlayer.on('seeked', () => {
      partySync.pushPlayerState(vjsPlayer, !vjsPlayer.paused())
    })

    vjsPlayer.on('error', () => {
      if (videoJsPlayer.value !== vjsPlayer) return
      onPlayerError?.(vjsPlayer.error())
    })

    // Track buffered amount for progress bar
    vjsPlayer.on('progress', () => {
      if (vjsPlayer.buffered().length > 0) {
        bufferedAmount.value = vjsPlayer.buffered().end(vjsPlayer.buffered().length - 1)
      }
    })

    // Check episode navigation buttons
    checkEpisodeNavigation()
  }

  function onPlayerReady() {
    if (playToken.value && videoJsPlayer.value) {
      setTimeout(() => setupXhrAuth('Ready'), 100)
    }

    wsStore.updatePlaybackStatus({
      isPlaying: true,
      mediaType: contentType.value,
      mediaGuid: uuid.value,
      mediaTitle: contentInfo.value?.title || contentInfo.value?.name || '',
      position: lastPosition.value,
      duration: videoDuration.value,
    })
    reportPlaybackStarted?.(lastPosition.value, videoDuration.value)

    if (lastPosition.value > 0 && videoJsPlayer.value.readyState() >= 1) {
      videoJsPlayer.value.currentTime(lastPosition.value)
    } else if (lastPosition.value > 0) {
      videoJsPlayer.value.one('loadedmetadata', () => {
        videoJsPlayer.value.currentTime(lastPosition.value)
      })
    }

    setupMediaSession()

    // Late joiner: request current state from host after player is ready
    partySync.requestLateJoinerSync()
  }

  function onTimeUpdate() {
    // Use playerState from mounted event
    if (!playerState.value) return

    try {
      const currentTime = playerState.value.currentTime || 0
      let playerDuration = playerState.value.duration

      // Update stream position for custom controls
      streamPosition.value = currentTime

      if (!playerDuration || !isFinite(playerDuration) || playerDuration === 0) {
        playerDuration = videoDuration.value
      }

      if (playerDuration > 0) {
        duration.value = playerDuration

        // Calculate real position for WebSocket (transcode start + stream position)
        const realPosition = transcodeStartPosition.value + currentTime

        // Update WebSocket with current playback status
        wsStore.updatePlaybackStatus({
          isPlaying: playerState.value.playing || false,
          mediaType: contentType.value,
          mediaGuid: uuid.value,
          mediaTitle: contentInfo.value?.title || contentInfo.value?.name || '',
          position: realPosition,
          duration: videoDuration.value,
        })

        // Save progress every 10 seconds (check if we crossed a 10-second boundary)
        const currentInterval = Math.floor(realPosition / 10)
        const lastInterval = Math.floor(lastPosition.value / 10)
        if (currentInterval > lastInterval || (realPosition > 5 && lastPosition.value === 0)) {
          updateProgress(realPosition, videoDuration.value)
          lastPosition.value = realPosition
        }
      }
    } catch (error) {
      // Player not fully initialized yet, ignore
      logger.debug('Player not ready for timeupdate:', error.message)
    }
  }

  async function onVideoEnded() {
    // Use playerState if available
    const dur = playerState.value?.duration || duration.value || videoDuration.value
    if (dur > 0) {
      updateProgress(dur, dur, { eventName: 'stop' })
    }

    // Clear playback status on video end
    wsStore.clearPlaybackStatus()

    const shouldAdvance =
      typeof shouldAutoAdvanceOnEnded === 'function'
        ? shouldAutoAdvanceOnEnded()
        : contentType.value === 'episode'
    if (shouldAdvance) {
      await playNextEpisode()
    }
  }

  // Save progress when video is paused (fallback for @pause event)
  function onVideoPause() {
    logger.debug('onVideoPause called (from @pause event)')
    // Use playerState from mounted event - it has reactive currentTime
    if (playerState.value) {
      const currentTime = playerState.value.currentTime || 0
      const dur = playerState.value.duration || videoDuration.value
      logger.debug(`onVideoPause via state: currentTime=${currentTime}, duration=${dur}`)
      updateProgress(currentTime, dur, { isPaused: true })
    } else if (videoJsPlayer.value && typeof videoJsPlayer.value.currentTime === 'function') {
      // Fallback to direct player access
      const currentTime = videoJsPlayer.value.currentTime()
      const dur = videoJsPlayer.value.duration() || videoDuration.value
      logger.debug(`onVideoPause via player: currentTime=${currentTime}, duration=${dur}`)
      updateProgress(currentTime, dur, { isPaused: true })
    } else {
      logger.debug('onVideoPause: no player state available')
    }
  }

  watch(
    () => [sessionId.value, playToken.value],
    () => {
      setupTrickplaySprites()
    },
  )

  onUnmounted(cancelTrickplayPolling)

  return {
    onPlayerMounted,
    onPlayerReady,
    onTimeUpdate,
    onVideoEnded,
    onVideoPause,
    trickplayManifest,
  }
}
