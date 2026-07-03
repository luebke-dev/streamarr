import { ref } from 'vue'
import { api } from 'boot/axios'
import { useInterval } from 'src/composables/useInterval'
import { getAccessToken } from 'src/utils/authStorage'

/**
 * Manages viewing-history progress for a media item:
 *   - loads the resume position from the backend (or watch-party state)
 *   - posts periodic progress updates while the player is running
 *   - persists final progress on page unload (via fetch + keepalive)
 *
 * The composable owns the 30s polling interval; the consumer is responsible
 * for calling startProgressUpdates() once the player is ready and
 * stopProgressUpdates() on teardown / state reset.
 *
 * Args (all reactive refs unless noted):
 *   - uuid             current media item id
 *   - contentType      'movie' | 'episode' | ...
 *   - authStore        pinia auth store (read-only, for `.user`)
 *   - partySync        watch-party sync helper (for applyResumePosition)
 *   - videoJsPlayer    ref<videojs.Player|null>
 *   - videoDuration    fallback duration when player.duration() is missing
 *   - duration         current player duration (used by saveProgressOnUnload)
 *   - sessionId, playToken  passed through unchanged for the unload handler
 *   - transcodeStartPosition  offset of the current transcode (stream time → real time)
 *
 * Returns: { lastPosition, loadViewingHistory, updateProgress,
 *            saveProgressOnUnload, startProgressUpdates, stopProgressUpdates }
 */
export function useViewingProgress({
  uuid,
  contentType,
  playlistId,
  playlistIndex,
  authStore,
  partySync,
  videoJsPlayer,
  contentInfo,
  videoDuration,
  duration,
  sessionId,
  playToken,
  transcodeStartPosition,
}) {
  const lastPosition = ref(0)

  function realPosition(streamTime) {
    return (transcodeStartPosition?.value || 0) + (streamTime || 0)
  }

  function progressExtraData() {
    if (!playlistId?.value) return null
    return {
      playlist_guid: playlistId.value,
      playlist_index: playlistIndex?.value ?? 0,
    }
  }

  function playbackPayload(currentTime, videoDur, { isPaused = false } = {}) {
    const durationSeconds = videoDur > 0 && isFinite(videoDur) ? Math.floor(videoDur) : null
    return {
      position_seconds: Math.max(0, Math.floor(currentTime || 0)),
      duration_seconds: durationSeconds,
      client_session_id: sessionId.value || playToken.value || null,
      device_id: authStore.deviceId || null,
      is_paused: isPaused,
      media_type: contentType.value,
      media_title: contentInfo?.value?.title || contentInfo?.value?.name || null,
      playlist_guid: playlistId?.value || null,
      playlist_index: playlistIndex?.value ?? null,
      extra_data: progressExtraData(),
    }
  }

  async function reportPlaystate(eventName, currentTime = 0, videoDur = null, options = {}) {
    const mediaGuid = options.uuid || uuid.value
    if (!authStore.user || !mediaGuid) return
    const endpoint =
      eventName === 'start'
        ? 'playing'
        : eventName === 'stop' || eventName === 'finish'
          ? 'stopped'
          : 'progress'
    try {
      await api.post(
        `/api/viewing-history/${mediaGuid}/${endpoint}`,
        playbackPayload(currentTime, videoDur, options),
      )
    } catch {
      // Silently fail on playstate updates
    }
  }

  async function loadViewingHistory() {
    // If in a watch party, use the party's current playback position
    if (partySync.applyResumePosition(lastPosition)) {
      return
    }

    try {
      const response = await api.get('/api/viewing-history', {
        params: {
          content_type: contentType.value,
          content_guid: uuid.value,
        },
      })

      if (response.data.items && response.data.items.length > 0) {
        const history = response.data.items[0]
        const progressSeconds = Number(history.progress_seconds || 0)
        const durationSeconds = Number(history.duration_seconds || 0)
        const nearEnd =
          durationSeconds > 0 &&
          (progressSeconds >= durationSeconds - 10 ||
            Number(history.progress_percentage || 0) >= 95)

        lastPosition.value = history.is_completed || nearEnd ? 0 : progressSeconds
      }
    } catch {
      // Silently fail if no history
    }
  }

  async function updateProgress(currentTime, videoDur, options = {}) {
    if (!authStore.user || !(options.uuid || uuid.value) || !videoDur) return
    await reportPlaystate(options.eventName || 'progress', currentTime, videoDur, {
      isPaused: Boolean(options.isPaused),
      uuid: options.uuid,
    })
  }

  function saveProgressOnUnload() {
    const token = getAccessToken()
    const baseUrl = api.defaults.baseURL || window.location.origin

    // Save viewing progress
    if (videoJsPlayer.value && duration.value > 0) {
      const currentTime = realPosition(videoJsPlayer.value.currentTime())
      const progressData = playbackPayload(currentTime, videoDuration.value || duration.value)
      // Use fetch with keepalive for unload - supports headers unlike sendBeacon
      fetch(`${baseUrl}/api/viewing-history/${uuid.value}/stopped`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify(progressData),
        keepalive: true,
      }).catch(() => {
        // Ignore errors during unload
      })
    }

    // Stop streaming session and cleanup (temp files + library file)
    if (sessionId.value && playToken.value) {
      fetch(`${baseUrl}/api/stream/${sessionId.value}?delete_library_file=true`, {
        method: 'DELETE',
        headers: {
          Authorization: `Bearer ${playToken.value}`,
        },
        keepalive: true,
      }).catch(() => {
        // Ignore errors during unload
      })
    }
  }

  const poller = useInterval(() => {
    if (
      videoJsPlayer.value &&
      typeof videoJsPlayer.value.paused === 'function' &&
      !videoJsPlayer.value.paused()
    ) {
      const currentTime = realPosition(videoJsPlayer.value.currentTime())
      let playerDuration = videoDuration.value

      if (!playerDuration || !isFinite(playerDuration) || playerDuration === 0) {
        playerDuration = videoJsPlayer.value.duration()
      }

      if (playerDuration > 0) {
        updateProgress(currentTime, playerDuration)
      }
    }
  }, 30000)

  return {
    lastPosition,
    loadViewingHistory,
    updateProgress,
    reportPlaybackStarted: (currentTime = 0, videoDur = null) =>
      reportPlaystate('start', currentTime, videoDur),
    reportPlaybackStopped: (currentTime = 0, videoDur = null) =>
      reportPlaystate('stop', currentTime, videoDur),
    saveProgressOnUnload,
    startProgressUpdates: poller.start,
    stopProgressUpdates: poller.stop,
  }
}
