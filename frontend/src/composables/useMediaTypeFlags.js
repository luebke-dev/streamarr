import { computed } from 'vue'
import { MediaTypes } from 'src/composables/useUnifiedMedia'

/**
 * Media-type boolean flags derived from the loaded media item.
 *
 * `isSeason`/`isEpisode` disambiguate series sub-types using the loaded
 * children (a season has episodes; an episode has none), so both the
 * `mediaItem` and `children` refs must be supplied.
 *
 * @param {Object} deps
 * @param {import('vue').Ref} deps.mediaItem - the loaded media item ref
 * @param {import('vue').Ref} deps.children - loaded children (seasons/episodes/tracks)
 */
export function useMediaTypeFlags({ mediaItem, children }) {
  // Media type detection - only from loaded item
  const mediaType = computed(() => {
    if (mediaItem.value?.media_type) {
      return mediaItem.value.media_type
    }
    return null
  })

  // Type checks
  const isMovie = computed(() => mediaType.value === MediaTypes.MOVIES)
  // A show is series type WITHOUT a parent (not a season or episode)
  const isShow = computed(
    () => mediaType.value === MediaTypes.SERIES && !mediaItem.value?.parent_guid,
  )
  // A season is series type WITH a parent but HAS children (episodes)
  const isSeason = computed(
    () =>
      mediaType.value === MediaTypes.SERIES &&
      mediaItem.value?.parent_guid &&
      children.value.length > 0,
  )
  // An episode is series type WITH a parent but has NO children
  const isEpisode = computed(
    () =>
      mediaType.value === MediaTypes.SERIES &&
      mediaItem.value?.parent_guid &&
      children.value.length === 0,
  )
  const isGame = computed(() => mediaType.value === MediaTypes.GAMES)
  const isMusic = computed(() => mediaType.value === MediaTypes.MUSIC)
  const isArtist = computed(() => mediaType.value === MediaTypes.ARTISTS)
  const isAlbum = computed(() => mediaType.value === MediaTypes.ALBUMS)
  const isSong = computed(() => mediaType.value === MediaTypes.SONGS)
  const isMusicType = computed(
    () => isMusic.value || isArtist.value || isAlbum.value || isSong.value,
  )
  const isBook = computed(() => mediaType.value === MediaTypes.BOOKS)
  const isContainerType = computed(
    () => isArtist.value || isAlbum.value || isShow.value || isSeason.value,
  )

  return {
    mediaType,
    isMovie,
    isShow,
    isSeason,
    isEpisode,
    isGame,
    isMusic,
    isArtist,
    isAlbum,
    isSong,
    isMusicType,
    isBook,
    isContainerType,
  }
}
