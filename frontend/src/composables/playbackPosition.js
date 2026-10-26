/**
 * Shared playback-position helpers.
 *
 * The "real" player time is the absolute media position. A partial transcode
 * starts partway into the media, so its timeline is *relative* and the offset
 * has to be added. Not every resumed stream is partial, though: a remux/HLS VOD
 * that covers the whole file keeps an absolute timeline while the response still
 * carries the resume position, and adding the offset there counted the resume
 * point twice.
 *
 * That is how watching_history ended up with progress beyond the media length
 * (Snowfall S03E07: 6574 s in a 2752 s file, offset 3822). The stored position
 * then pointed past the end, resume sought there, the file ended immediately and
 * the episode looked like it was playing again.
 *
 * Both the Watch Party sync path (usePartySync) and the remote-control receiver
 * (useRemoteControlReceiver) must compute this identically, so the logic lives
 * here to keep them from drifting.
 */

/** A stream whose own duration is within this many seconds of the media duration
 * covers the whole media and therefore uses an absolute timeline. */
const FULL_TIMELINE_TOLERANCE_SECONDS = 5

function unwrap(value) {
  return value && typeof value === 'object' ? value.value || 0 : value || 0
}

/**
 * Offset that actually applies to the current player timeline.
 *
 * @param {number} playerDuration - duration the player reports for its stream.
 * @param {number} mediaDuration - duration of the media item itself.
 * @param {{ value?: number } | number | null | undefined} transcodeStartPosition
 * @returns {number} offset in seconds to add to `player.currentTime()`.
 */
export function timelineOffset(playerDuration, mediaDuration, transcodeStartPosition) {
  const offset = unwrap(transcodeStartPosition)
  if (!offset) return 0

  // Unknown durations: keep the historical behaviour rather than inventing one.
  if (!playerDuration || !mediaDuration) return offset

  const coversWholeMedia =
    playerDuration >= mediaDuration - FULL_TIMELINE_TOLERANCE_SECONDS
  return coversWholeMedia ? 0 : offset
}

/**
 * Absolute media position for a Video.js player, given the transcode start
 * offset.
 *
 * @param {object} player - Video.js player handle.
 * @param {{ value?: number } | number | null | undefined} transcodeStartPosition
 *   - the current transcode offset, either a ref or a plain number.
 * @param {number} [mediaDuration] - duration of the media item, used to detect a
 *   stream that already starts at the beginning.
 * @returns {number} absolute position in seconds, never beyond the media length.
 */
export function realPlayerTime(player, transcodeStartPosition, mediaDuration = 0) {
  const currentTime = player?.currentTime?.() || 0
  const playerDuration = player?.duration?.() || 0
  const position = currentTime + timelineOffset(playerDuration, mediaDuration, transcodeStartPosition)

  // Never report a position beyond the media: a wrong value here poisons the
  // resume point of the next playback.
  return mediaDuration > 0 ? Math.min(position, mediaDuration) : position
}
