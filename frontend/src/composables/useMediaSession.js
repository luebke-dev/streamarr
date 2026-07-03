/**
 * MediaSession composable for the play page.
 *
 * Wraps navigator.mediaSession metadata + action-handler setup so the
 * page does not have to keep the boilerplate inline. Registers play /
 * pause / seekforward / seekbackward handlers (and nexttrack /
 * previoustrack for episode content) and clears them on unmount so
 * media keys do not keep firing into a stale player after the user
 * leaves the page.
 *
 * Inputs (all reactive refs):
 *   - contentInfo: ref of the loaded media item
 *   - contentType: ref<string> ('movie' | 'episode' | ...)
 *   - videoJsPlayer: ref to the underlying video.js player (for
 *       play / pause / currentTime() control)
 *   - playNextEpisode: () => Promise<void>  — episode 'nexttrack'
 *   - playPreviousEpisode: () => Promise<void>  — episode 'previoustrack'
 *   - getTmdbImageUrl: (path, size) => string  — artwork helper
 */

import { onBeforeUnmount } from 'vue'
import { logger } from 'src/utils/logger'

const HANDLED_ACTIONS = [
  'play',
  'pause',
  'seekforward',
  'seekbackward',
  'nexttrack',
  'previoustrack',
]

export function useMediaSession({
  contentInfo,
  contentType,
  videoJsPlayer,
  playNextEpisode,
  playPreviousEpisode,
  getTmdbImageUrl,
}) {
  const setupMediaSession = () => {
    if (!('mediaSession' in navigator)) {
      logger.debug('MediaSession API not supported')
      return
    }

    // Set metadata for the media session
    const title = contentInfo.value?.title || contentInfo.value?.name || 'Unknown'
    let artist = ''
    let album = ''

    if (contentType.value === 'episode') {
      artist = contentInfo.value?.show_name || ''
      album = `Season ${contentInfo.value?.season_number || ''}`
    }

    navigator.mediaSession.metadata = new MediaMetadata({
      title: title,
      artist: artist,
      album: album,
      artwork:
        contentInfo.value?.poster_path || contentInfo.value?.still_path
          ? [
              {
                src: getTmdbImageUrl(
                  contentInfo.value?.poster_path || contentInfo.value?.still_path,
                  'w500',
                ),
                sizes: '500x750',
                type: 'image/jpeg',
              },
            ]
          : [],
    })

    // Only register next/previous handlers for episodes
    if (contentType.value === 'episode') {
      navigator.mediaSession.setActionHandler('nexttrack', async () => {
        logger.debug('MediaSession: nexttrack action triggered')
        await playNextEpisode()
      })

      navigator.mediaSession.setActionHandler('previoustrack', async () => {
        logger.debug('MediaSession: previoustrack action triggered')
        await playPreviousEpisode()
      })
    } else {
      navigator.mediaSession.setActionHandler('nexttrack', null)
      navigator.mediaSession.setActionHandler('previoustrack', null)
    }

    // Handle play/pause
    navigator.mediaSession.setActionHandler('play', () => {
      if (videoJsPlayer.value) {
        videoJsPlayer.value.play()
      }
    })

    navigator.mediaSession.setActionHandler('pause', () => {
      if (videoJsPlayer.value) {
        videoJsPlayer.value.pause()
      }
    })

    // Handle seek forward/backward
    navigator.mediaSession.setActionHandler('seekforward', (details) => {
      if (videoJsPlayer.value) {
        const skipTime = details.seekOffset || 10
        videoJsPlayer.value.currentTime(videoJsPlayer.value.currentTime() + skipTime)
      }
    })

    navigator.mediaSession.setActionHandler('seekbackward', (details) => {
      if (videoJsPlayer.value) {
        const skipTime = details.seekOffset || 10
        videoJsPlayer.value.currentTime(Math.max(0, videoJsPlayer.value.currentTime() - skipTime))
      }
    })

    logger.debug('MediaSession handlers registered')
  }

  // Auto-clear handlers + metadata when the page unmounts so media
  // keys do not continue firing into a torn-down player.
  onBeforeUnmount(() => {
    if (!('mediaSession' in navigator)) return
    for (const action of HANDLED_ACTIONS) {
      try {
        navigator.mediaSession.setActionHandler(action, null)
      } catch {
        // browser may not support an action; ignore
      }
    }
    navigator.mediaSession.metadata = null
  })

  return { setupMediaSession }
}
