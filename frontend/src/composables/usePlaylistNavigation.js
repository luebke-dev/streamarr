import { computed, ref } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

function queueItemToPlayType(item) {
  switch (item?.item_type) {
    case 'episode':
    case 'show':
      return 'episode'
    case 'game':
      return 'game'
    case 'music':
      return 'music'
    case 'book':
    case 'audiobook':
      return 'book'
    case 'movie':
    default:
      return 'movie'
  }
}

function queueItemToNavigationData(item) {
  if (!item) return null
  return {
    guid: item.media_item_guid,
    title: item.title,
    name: item.title,
    poster_path: item.poster_path,
    backdrop_path: item.backdrop_path,
    queue_index: item.queue_index,
    item_type: item.item_type,
  }
}

export function usePlaylistNavigation({
  playlistId,
  playlistIndex,
  contentType,
  router,
  episodeNavigation,
}) {
  const hasPreviousPlaylistItem = ref(false)
  const hasNextPlaylistItem = ref(false)
  const previousPlaylistItemData = ref(null)
  const nextPlaylistItemData = ref(null)

  function playlistItemRoute(item) {
    return {
      path: `/play/${item.media_item_guid || item.guid}`,
      query: {
        type: queueItemToPlayType(item),
        playlist: playlistId.value,
        playlist_index: item.queue_index,
      },
    }
  }

  function resetPlaylistNavigation() {
    hasPreviousPlaylistItem.value = false
    hasNextPlaylistItem.value = false
    previousPlaylistItemData.value = null
    nextPlaylistItemData.value = null
  }

  async function checkPlaylistNavigation() {
    resetPlaylistNavigation()
    if (!playlistId.value) return

    try {
      const response = await api.get(`/api/playlists/${playlistId.value}/queue`, {
        params: { start_index: playlistIndex.value },
      })
      const queue = response.data
      previousPlaylistItemData.value = queueItemToNavigationData(queue.previous_item)
      nextPlaylistItemData.value = queueItemToNavigationData(queue.next_item)
      hasPreviousPlaylistItem.value = !!previousPlaylistItemData.value
      hasNextPlaylistItem.value = !!nextPlaylistItemData.value
    } catch (error) {
      logger.debug('Failed to load playlist navigation:', error)
      resetPlaylistNavigation()
    }
  }

  async function playPreviousPlaylistItem() {
    if (!previousPlaylistItemData.value) return
    router.replace(playlistItemRoute(previousPlaylistItemData.value))
  }

  async function playNextPlaylistItem() {
    if (nextPlaylistItemData.value) {
      router.replace(playlistItemRoute(nextPlaylistItemData.value))
    } else {
      router.back()
    }
  }

  const showPlaybackNavigation = computed(() => contentType.value === 'episode' || !!playlistId.value)
  const hasPreviousPlaybackItem = computed(() =>
    playlistId.value ? hasPreviousPlaylistItem.value : episodeNavigation.hasPreviousEpisode.value,
  )
  const hasNextPlaybackItem = computed(() =>
    playlistId.value ? hasNextPlaylistItem.value : episodeNavigation.hasNextEpisode.value,
  )
  const previousPlaybackItemData = computed(() =>
    playlistId.value ? previousPlaylistItemData.value : episodeNavigation.previousEpisodeData.value,
  )
  const nextPlaybackItemData = computed(() =>
    playlistId.value ? nextPlaylistItemData.value : episodeNavigation.nextEpisodeData.value,
  )
  const playPreviousPlaybackItem = () =>
    playlistId.value ? playPreviousPlaylistItem() : episodeNavigation.playPreviousEpisode()
  const playNextPlaybackItem = () =>
    playlistId.value ? playNextPlaylistItem() : episodeNavigation.playNextEpisode()

  return {
    hasPreviousPlaylistItem,
    hasNextPlaylistItem,
    previousPlaylistItemData,
    nextPlaylistItemData,
    resetPlaylistNavigation,
    checkPlaylistNavigation,
    playPreviousPlaylistItem,
    playNextPlaylistItem,
    showPlaybackNavigation,
    hasPreviousPlaybackItem,
    hasNextPlaybackItem,
    previousPlaybackItemData,
    nextPlaybackItemData,
    playPreviousPlaybackItem,
    playNextPlaybackItem,
  }
}
