import { api } from 'boot/axios'
import { watch } from 'vue'
import { getTrickplayManifest } from 'src/composables/usePlay'
import { logger } from 'src/utils/logger'

let spriteThumbnailsPluginPromise = null

async function loadSpriteThumbnailsPlugin() {
  if (!spriteThumbnailsPluginPromise) {
    spriteThumbnailsPluginPromise = import('videojs-sprite-thumbnails')
  }
  return spriteThumbnailsPluginPromise
}

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
 *   - reportPlaybackStopped(t, dur) report native playstate stop
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
  reportPlaybackStopped,
  setupMediaSession,
  checkEpisodeNavigation,
  shouldAutoAdvanceOnEnded,
  playNextEpisode,
}) {
  const absoluteApiUrl = (path) => {
    if (!path) return ''
    if (/^https?:\/\//i.test(path)) return path
    const baseUrl = api.defaults.baseURL || window.location.origin
    return `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
  }

  async function setupTrickplaySprites(vjsPlayer) {
    if (!sessionId.value || !playToken.value) return

    try {
      await loadSpriteThumbnailsPlugin()
      if (!vjsPlayer?.spriteThumbnails) return

      const manifest = await getTrickplayManifest(sessionId.value, playToken.value)
      if (!manifest.ready || !manifest.sprites?.length) return

      vjsPlayer.spriteThumbnails({
        interval: manifest.interval_seconds || 10,
        urlArray: manifest.sprites.map((sprite) => absoluteApiUrl(sprite.url)),
        width: manifest.thumbnail_width || 160,
        height: manifest.thumbnail_height || 90,
        columns: manifest.columns || 10,
        rows: manifest.rows || 10,
      })
    } catch (error) {
      logger.debug('Failed to initialize trickplay thumbnails from manifest:', error)
    }
  }

  function onPlayerMounted({ video, player: vjsPlayer, state }) {
    videoJsPlayer.value = vjsPlayer
    playerState.value = state
    videoElement.value = video

    if (playToken.value) {
      setupXhrAuth('Mount')
    }

    setupTrickplaySprites(vjsPlayer)

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
      reportPlaybackStopped?.(dur, dur)
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
      if (videoJsPlayer.value) {
        setupTrickplaySprites(videoJsPlayer.value)
      }
    },
  )

  return {
    onPlayerMounted,
    onPlayerReady,
    onTimeUpdate,
    onVideoEnded,
    onVideoPause,
  }
}
