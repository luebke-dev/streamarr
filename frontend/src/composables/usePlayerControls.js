import { logger } from 'src/utils/logger'
import { checkPositionAvailable } from 'src/composables/usePlay'

/**
 * Handlers wired into <CustomPlayerControls>: seek, audio-track switch,
 * quality switch, play/pause, mute, volume, fullscreen.
 *
 * The handlers delegate stream re-encoding to swapStreamSource (from
 * useStreamSwap) and otherwise drive the Video.js player directly.
 *
 * 3-tier seek strategy:
 *   1. Client buffer covers position → instant seek (no network)
 *   2. Server has the segment       → let Video.js fetch it
 *   3. Neither                       → start a new transcode
 *
 * Args (all reactive refs unless noted):
 *   - videoJsPlayer
 *   - playerWrapperRef          DOM element used for fullscreen
 *   - isPlaying, isSeeking
 *   - transcodeStartPosition
 *   - currentAudioTrackIndex, currentMediaSourceId, directStreamUrl
 *   - sessionId, playToken
 *   - swapStreamSource          from useStreamSwap
 *   - isPositionBuffered        from useStreamSwap (Tier-1 seek check)
 *
 * Returns: { handleSeek, handleAudioTrackChange, handleQualityChange,
 *            togglePlayPause, toggleMute, setVolume, toggleFullscreen }
 */
export function usePlayerControls({
  videoJsPlayer,
  playerWrapperRef,
  isPlaying,
  isSeeking,
  transcodeStartPosition,
  currentAudioTrackIndex,
  currentMediaSourceId,
  directStreamUrl,
  sessionId,
  playToken,
  swapStreamSource,
  isPositionBuffered,
}) {
  async function handleSeek(position) {
    if (isSeeking.value) return

    if (directStreamUrl.value) {
      if (videoJsPlayer.value) {
        videoJsPlayer.value.currentTime(position)
      }
      return
    }

    isSeeking.value = true
    try {
      // --- Tier 1: Check client buffer ---
      const streamRelativePosition = position - transcodeStartPosition.value

      if (streamRelativePosition >= 0 && isPositionBuffered(streamRelativePosition)) {
        logger.debug(
          `[Seek] Tier 1 — client buffered, seeking to ${streamRelativePosition}s (absolute: ${position}s)`,
        )
        if (videoJsPlayer.value) {
          videoJsPlayer.value.currentTime(streamRelativePosition)
        }
        return
      }

      // --- Tier 2: Check server availability ---
      if (streamRelativePosition >= 0 && sessionId.value && playToken.value) {
        try {
          const check = await checkPositionAvailable(
            sessionId.value,
            playToken.value,
            position,
            transcodeStartPosition.value,
          )
          if (check.available) {
            logger.debug(
              `[Seek] Tier 2 — server has segment ${check.segment_index}, seeking to ${check.stream_position}s`,
            )
            if (videoJsPlayer.value) {
              videoJsPlayer.value.currentTime(check.stream_position)
            }
            return
          }
          logger.debug(
            `[Seek] Tier 2 — server does not have segment (reason: ${check.reason}), falling through to new transcode`,
          )
        } catch (e) {
          logger.warn('[Seek] Tier 2 check failed, falling through:', e)
        }
      }

      // --- Tier 3: Start new transcode ---
      logger.debug(`[Seek] Tier 3 — starting new transcode at ${position}s`)

      const options = {
        video_codec: 'h264',
        audio_codec: 'aac',
        audio_bitrate: '128k',
      }

      // Preserve current audio track selection during seek
      if (currentAudioTrackIndex.value !== null) {
        options.audio_track = currentAudioTrackIndex.value
      }
      if (currentMediaSourceId.value) {
        options.media_source_id = currentMediaSourceId.value
      }

      await swapStreamSource({ position, options, label: 'Seek' })
    } finally {
      isSeeking.value = false
    }
  }

  // Audio track change — retranscode at current position with the new audio track
  async function handleAudioTrackChange(audioTrackIndex) {
    logger.debug('[AudioTrack] handleAudioTrackChange called with index:', audioTrackIndex)
    if (isSeeking.value) {
      logger.debug('[AudioTrack] Skipped — already seeking')
      return
    }

    // Persist audio track selection for future seeks
    currentAudioTrackIndex.value = audioTrackIndex

    const currentStreamPos = videoJsPlayer.value ? videoJsPlayer.value.currentTime() : 0
    const absolutePosition = transcodeStartPosition.value + currentStreamPos

    logger.debug(
      `[AudioTrack] Switching to audio track ${audioTrackIndex} at position ${absolutePosition}s`,
    )

    const options = {
      video_codec: 'h264',
      audio_codec: 'aac',
      audio_bitrate: '128k',
      audio_track: audioTrackIndex,
    }
    if (currentMediaSourceId.value) {
      options.media_source_id = currentMediaSourceId.value
    }

    await swapStreamSource({
      position: absolutePosition,
      options,
      label: 'AudioTrack',
      persistAudioTrack: false,
    })
  }

  // Quality change from CustomPlayerControls
  async function handleQualityChange(level) {
    if (isSeeking.value) return
    if (level.source !== 'transcode' && !level.file_guid) return

    const currentStreamPos = videoJsPlayer.value ? videoJsPlayer.value.currentTime() : 0
    const absolutePosition = transcodeStartPosition.value + currentStreamPos

    const options = {
      video_codec: 'h264',
      audio_codec: 'aac',
      audio_bitrate: '128k',
    }
    if (level.source === 'transcode' && level.height) {
      logger.debug(
        `[Quality] Switching to ${level.label} (${level.height}p) transcode at position ${absolutePosition}s`,
      )
      const width = Math.round((level.height * 16) / 9)
      // Round to nearest even (H.264 requirement)
      const evenWidth = width % 2 === 0 ? width : width + 1
      options.resolution = `${evenWidth}x${level.height}`
    } else {
      logger.debug(
        `[Quality] Switching to media source ${level.file_guid} at position ${absolutePosition}s`,
      )
    }

    if (currentAudioTrackIndex.value !== null) {
      options.audio_track = currentAudioTrackIndex.value
    }

    if (level.file_guid) {
      options.media_source_id = level.file_guid
    } else if (currentMediaSourceId.value) {
      options.media_source_id = currentMediaSourceId.value
    }

    await swapStreamSource({
      position: absolutePosition,
      options,
      label: level.file_guid ? 'MediaSource' : 'Quality',
    })
  }

  function togglePlayPause() {
    if (!videoJsPlayer.value) return
    if (isPlaying.value) {
      videoJsPlayer.value.pause()
    } else {
      videoJsPlayer.value.play()
    }
  }

  function toggleMute(muted) {
    if (videoJsPlayer.value) {
      videoJsPlayer.value.muted(muted)
    }
  }

  function setVolume(volume) {
    if (videoJsPlayer.value) {
      videoJsPlayer.value.volume(volume)
    }
  }

  // Toggle fullscreen using the native browser Fullscreen API so that the
  // player truly covers the whole screen rather than just the layout area.
  function toggleFullscreen() {
    const el = playerWrapperRef.value
    if (!el) return

    if (!document.fullscreenElement) {
      const request =
        el.requestFullscreen ||
        el.webkitRequestFullscreen ||
        el.mozRequestFullScreen ||
        el.msRequestFullscreen
      if (request) request.call(el)
    } else {
      const exit =
        document.exitFullscreen ||
        document.webkitExitFullscreen ||
        document.mozCancelFullScreen ||
        document.msExitFullscreen
      if (exit) exit.call(document)
    }
  }

  return {
    handleSeek,
    handleAudioTrackChange,
    handleQualityChange,
    togglePlayPause,
    toggleMute,
    setVolume,
    toggleFullscreen,
  }
}
