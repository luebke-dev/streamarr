/**
 * Episode-navigation composable for the play page.
 *
 * Wraps GET /api/media/{uuid}/previous-episode and
 * GET /api/media/{uuid}/next-episode plus the router.replace navigation
 * helpers used by the player to jump between episodes.
 *
 * Usage:
 *   const {
 *     hasPreviousEpisode,
 *     hasNextEpisode,
 *     previousEpisodeData,
 *     nextEpisodeData,
 *     checkEpisodeNavigation,
 *     playNextEpisode,
 *     playPreviousEpisode,
 *     resetEpisodeNavigation,
 *   } = useEpisodeNavigation({ uuid, contentType, router })
 */

import { ref } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

export function useEpisodeNavigation({ uuid, contentType, router }) {
  const hasPreviousEpisode = ref(false)
  const hasNextEpisode = ref(false)
  const previousEpisodeData = ref(null)
  const nextEpisodeData = ref(null)

  const resetEpisodeNavigation = () => {
    hasPreviousEpisode.value = false
    hasNextEpisode.value = false
    previousEpisodeData.value = null
    nextEpisodeData.value = null
  }

  const checkEpisodeNavigation = async () => {
    logger.debug('[useEpisodeNavigation] called, contentType:', contentType.value)
    if (contentType.value !== 'episode') {
      logger.debug('[useEpisodeNavigation] Not an episode, skipping navigation check')
      return
    }

    try {
      logger.debug('[useEpisodeNavigation] Checking previous/next episode for:', uuid.value)
      const [prevRes, nextRes] = await Promise.all([
        api.get(`/api/media/${uuid.value}/previous-episode`).catch((e) => {
          logger.debug('[useEpisodeNavigation] Previous episode check failed:', e)
          return null
        }),
        api.get(`/api/media/${uuid.value}/next-episode`).catch((e) => {
          logger.debug('[useEpisodeNavigation] Next episode check failed:', e)
          return null
        }),
      ])

      previousEpisodeData.value = prevRes?.data?.previous_episode || null
      nextEpisodeData.value = nextRes?.data?.next_episode || null
      hasPreviousEpisode.value = !!previousEpisodeData.value
      hasNextEpisode.value = !!nextEpisodeData.value
      logger.debug(
        '[useEpisodeNavigation] result - hasPrevious:',
        hasPreviousEpisode.value,
        'hasNext:',
        hasNextEpisode.value,
      )
    } catch (error) {
      logger.error('[useEpisodeNavigation] Episode navigation check error:', error)
    }
  }

  // Navigate using the data already fetched by checkEpisodeNavigation(), so the
  // target always matches what the player controls display and no redundant
  // round-trip runs on click.
  const playPreviousEpisode = () => {
    const previousEpisode = previousEpisodeData.value

    if (previousEpisode && previousEpisode.guid) {
      router.replace({
        path: `/play/${previousEpisode.guid}`,
        query: { type: 'episode' },
      })
    } else {
      logger.debug('No previous episode available')
    }
  }

  const playNextEpisode = () => {
    const nextEpisode = nextEpisodeData.value

    if (nextEpisode && nextEpisode.guid) {
      router.replace({
        path: `/play/${nextEpisode.guid}`,
        query: { type: 'episode' },
      })
    } else {
      // No next episode available, go back
      router.back()
    }
  }

  return {
    hasPreviousEpisode,
    hasNextEpisode,
    previousEpisodeData,
    nextEpisodeData,
    checkEpisodeNavigation,
    playPreviousEpisode,
    playNextEpisode,
    resetEpisodeNavigation,
  }
}
