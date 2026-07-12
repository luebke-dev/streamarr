/**
 * Shared playback-position helpers.
 *
 * The "real" player time is the absolute media position, accounting for the
 * offset introduced when the current stream is a partial transcode that
 * starts partway into the media. Both the Watch Party sync path
 * (usePartySync) and the remote-control receiver (useRemoteControlReceiver)
 * must compute this identically, so the logic lives here to keep them from
 * drifting.
 */

/**
 * Absolute media position for a Video.js player, given the transcode start
 * offset.
 *
 * @param {object} player - Video.js player handle.
 * @param {{ value?: number } | number | null | undefined} transcodeStartPosition
 *   - the current transcode offset, either a ref or a plain number.
 * @returns {number} absolute position in seconds.
 */
export function realPlayerTime(player, transcodeStartPosition) {
  const offset =
    transcodeStartPosition && typeof transcodeStartPosition === 'object'
      ? transcodeStartPosition.value || 0
      : transcodeStartPosition || 0
  return offset + (player?.currentTime?.() || 0)
}
