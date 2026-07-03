import { logger } from 'src/utils/logger'
import {
  seekPlayback as seekUnifiedPlayback,
  getPlaylistUrl,
} from 'src/composables/usePlay'
import { useStreamReadiness } from 'src/composables/useStreamReadiness'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'

/**
 * Helpers for swapping the active HLS stream source on a Video.js player
 * without re-mounting the component. Used by Tier-3 seek, audio-track
 * switch and quality-switch — all three perform the same sequence:
 *
 *   start new transcode → pause current → wait for playlist →
 *   swap refs → load new src → re-attach XHR auth → play
 *
 * Also exposes:
 *   - isPositionBuffered(rel)  : Tier-1 seek check
 *   - abortPendingHlsRequests(): cancel in-flight VHS segment loaders
 *   - setupXhrAuth(label)      : re-attach the bearer-token beforeRequest
 *                                hook (must be called after any src() reset)
 *
 * Args (all reactive refs unless noted):
 *   - videoJsPlayer
 *   - playToken
 *   - sessionId
 *   - uuid
 *   - transcodeStartPosition
 *   - streamPosition
 *   - currentAudioTrackIndex
 *   - playbackTargetOptions
 *   - isSeeking
 *   - onSwapError(label)  optional callback invoked when a swap fails
 */
export function useStreamSwap({
  videoJsPlayer,
  playToken,
  sessionId,
  uuid,
  transcodeStartPosition,
  streamPosition,
  currentAudioTrackIndex,
  currentMediaSourceId,
  playbackTargetOptions,
  directStreamUrl,
  isSeeking,
  onSwapError,
}) {
  const { waitForHlsStreamReady } = useStreamReadiness()
  const streamSwapTimers = useTimeoutRegistry()

  // Check if a stream-relative position is within any client-buffered range
  function isPositionBuffered(targetPosition) {
    if (!videoJsPlayer.value) return false

    const buffered = videoJsPlayer.value.buffered()
    const absolutePosition = transcodeStartPosition.value + targetPosition

    for (let i = 0; i < buffered.length; i++) {
      const start = transcodeStartPosition.value + buffered.start(i)
      const end = transcodeStartPosition.value + buffered.end(i)

      // Add small tolerance (2 seconds) for near-buffered positions
      if (absolutePosition >= start - 2 && absolutePosition <= end + 2) {
        return true
      }
    }
    return false
  }

  // Safely abort in-flight HLS segment requests (guards against uninitialised VHS)
  function abortPendingHlsRequests() {
    try {
      const tech = videoJsPlayer.value?.tech?.({ IWillNotUseThisInPlugins: true })
      const mpc = tech?.vhs?.masterPlaylistController_
      if (mpc) {
        mpc.mainSegmentLoader_?.abort()
        mpc.audioSegmentLoader_?.abort()
      }
    } catch (e) {
      logger.debug('Could not abort pending HLS requests:', e)
    }
  }

  // Re-configure the VHS XHR beforeRequest hook (lost after src() resets the tech)
  function setupXhrAuth(logLabel = 'Stream') {
    try {
      const tech = videoJsPlayer.value?.tech?.({ IWillNotUseThisInPlugins: true })
      if (tech?.vhs) {
        tech.vhs.xhr.beforeRequest = (reqOptions) => {
          reqOptions.headers = reqOptions.headers || {}
          reqOptions.headers.Authorization = `Bearer ${playToken.value}`
          return reqOptions
        }
        logger.debug(`[${logLabel}] Re-configured XHR auth for new source`)
      }
    } catch (e) {
      logger.debug(`[${logLabel}] Could not re-configure XHR auth:`, e)
    }
  }

  // Swap the active stream source by requesting a new transcode at the
  // given position with the given options. Returns true on success.
  async function swapStreamSource({ position, options, label, persistAudioTrack = true }) {
    isSeeking.value = true
    const oldSessionId = sessionId.value

    try {
      const seekOptions = {
        ...(playbackTargetOptions?.value || {}),
        ...(options || {}),
      }
      const seekResponse = await seekUnifiedPlayback(uuid.value, position, oldSessionId, seekOptions)

      logger.debug(`[${label}] Seek response:`, seekResponse)

      const newPlayToken = seekResponse.token
      const newSessionId = seekResponse.session_id
      const newStartPosition = seekResponse.start_position || position

      // Stop old playback immediately (BEFORE waiting for new playlist)
      if (videoJsPlayer.value) {
        videoJsPlayer.value.pause()
        abortPendingHlsRequests()
      }

      // Wait until the NEW playlist is actually servable.
      // Do NOT update refs yet — keep the old session identifiers valid until
      // the new playlist is confirmed servable.
      const playlistReady = await waitForHlsStreamReady(newSessionId, newPlayToken)

      if (!playlistReady) {
        logger.warn(`[${label}] Stream not ready, aborting swap`)
        onSwapError?.(label)
        return false
      }

      // NOW update refs
      playToken.value = newPlayToken
      sessionId.value = newSessionId
      directStreamUrl.value = seekResponse.direct_file_url || ''
      transcodeStartPosition.value = newStartPosition
      streamPosition.value = 0
      if (seekResponse.media_source_id) {
        currentMediaSourceId.value = seekResponse.media_source_id
      } else if (options?.media_source_id) {
        currentMediaSourceId.value = options.media_source_id
      }

      if (persistAudioTrack && seekResponse.audio_track != null) {
        currentAudioTrackIndex.value = seekResponse.audio_track
      }

      const newPlaylistUrl = getPlaylistUrl(newSessionId, newPlayToken)

      if (videoJsPlayer.value) {
        // Clear any previous error state so the player accepts a new source
        if (videoJsPlayer.value.error()) {
          videoJsPlayer.value.error(null)
        }

        videoJsPlayer.value.src({
          src: newPlaylistUrl,
          type: 'application/x-mpegURL',
        })

        // Try immediately and also after a short delay (tech might not be ready yet)
        setupXhrAuth(label)
        streamSwapTimers.schedule(() => setupXhrAuth(label), 100)

        videoJsPlayer.value.play().catch((e) => {
          logger.warn('Autoplay prevented:', e)
        })
      }
      return true
    } catch (error) {
      logger.error(`${label} swap failed:`, error)
      return false
    } finally {
      isSeeking.value = false
    }
  }

  return {
    isPositionBuffered,
    abortPendingHlsRequests,
    setupXhrAuth,
    swapStreamSource,
  }
}
