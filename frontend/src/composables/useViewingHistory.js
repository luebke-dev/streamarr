import { useRouter } from 'vue-router'
import { api } from 'boot/axios'
import { getMediaImageUrl, formatEpisodeTitle } from 'src/composables/useMediaFormatters'
import { logger } from 'src/utils/logger'
import { overlayServeUrl } from 'src/utils/posters'

export function useViewingHistory() {
  const router = useRouter()

  function getPosterUrl(item) {
    // Prefer an overlay-rendered poster for local movies/shows. Episodes
    // and music items fall through to the existing artwork resolver.
    const overlay = overlayServeUrl(item?.media_item, 'POSTER')
    if (overlay) return overlay
    return getMediaImageUrl(item.media_item, { preferBackdrop: true })
  }

  function getTitle(item, fallback = '') {
    if (item.content_type === 'movie') {
      return item.media_item?.title || fallback
    }
    return formatEpisodeTitle({
      showTitle: item.show_title,
      seasonNumber: item.season_number,
      episodeNumber: item.episode_number,
      episodeTitle: item.media_item?.title,
      fallback,
    })
  }

  function navigateToPlay(item) {
    const contentType = item.content_type
    const guid = contentType === 'movie' ? item.movie_guid : item.episode_guid
    router.push({
      path: `/play/${guid}`,
      query: { type: contentType },
    })
  }

  async function removeItem(item, itemsRef) {
    try {
      await api.delete(`/api/viewing-history/${item.guid}`)
      itemsRef.value = itemsRef.value.filter((i) => i.guid !== item.guid)
    } catch (error) {
      logger.error('Failed to remove viewing history item:', error)
    }
  }

  return { getPosterUrl, getTitle, navigateToPlay, removeItem }
}
