<template>
  <div class="media-detail-page">
    <!-- Loading Indicator -->
    <MediaLoadingState v-if="loading" />

    <!-- Error State -->
    <MediaErrorState
      v-else-if="error"
      :message="error"
      :back-label="backLabel"
      :back-route="backRoute"
    />

    <!-- Media Details -->
    <div v-else-if="mediaItem" class="media-detail-content">
      <!-- Hero Section -->
      <MediaHeroSection
        :backdrop-url="heroBackdropUrl"
        :poster-url="heroPosterUrl"
        :title="heroTitle"
        :original-title="isEpisode || isSong ? mediaItem.title : mediaItem.original_title"
        :tagline="mediaItem.tagline"
        :placeholder-icon="placeholderIcon"
        :placeholder-text="placeholderText"
        :poster-width="isMusicType ? '180px' : '150px'"
        :poster-height="isMusicType ? '180px' : '225px'"
      >
        <template #back-button>
          <q-btn
            icon="mdi-arrow-left"
            :label="$q.screen.gt.sm ? $t('common.back') : ''"
            flat
            dense
            size="md"
            text-color="white"
            class="no-background"
            @click="$router.push(backRoute)"
          />
        </template>

        <template #meta-chips>
          <MediaMetaChips
            :year="mediaYear"
            :status="mediaStatus"
            :status-label="mediaStatusLabel"
            :status-color="mediaStatusColor"
            :content-rating="mediaItem?.content_rating"
            :min-age="mediaItem?.min_age"
            chip-size="sm"
          >
            <template #custom-chips>
              <!-- Type-specific chips -->
              <q-chip
                v-if="isShow && mediaItem.status"
                :label="mediaItem.status"
                :color="getStatusColor(mediaItem.status)"
                text-color="white"
                size="sm"
                class="q-mr-sm"
              />
              <q-chip
                v-if="isMovie && mediaItem.runtime"
                :label="formatRuntime(mediaItem.runtime)"
                color="info"
                text-color="white"
                size="sm"
                class="q-mr-sm"
              />
              <q-chip
                v-if="isAlbum && children.length > 0"
                :label="`${children.length} ${children.length === 1 ? 'Track' : 'Tracks'}`"
                color="info"
                text-color="white"
                size="sm"
                class="q-mr-sm"
              />
              <q-chip
                v-if="mediaItem.genres && mediaItem.genres.length > 0"
                :label="formatGenres(mediaItem.genres)"
                color="grey-7"
                text-color="white"
                size="sm"
              />
              <q-chip
                v-for="platform in mediaItem.platforms || []"
                :key="platform.id"
                color="blue-grey-7"
                text-color="white"
                size="sm"
              >
                <q-avatar v-if="platform.logo_url" size="18px" class="q-mr-xs">
                  <img :src="platform.logo_url" :alt="platform.name" />
                </q-avatar>
                <q-icon v-else name="mdi-gamepad-variant" size="14px" class="q-mr-xs" />
                {{ platform.name }}
              </q-chip>
            </template>
          </MediaMetaChips>
        </template>

        <template #actions>
          <MediaActionButtons
            :show-play="hasPlayableContent || isUnavailable"
            :show-add-to-list="true"
            :show-favorite="true"
            :show-like="!isContainerType && !isUnavailable"
            :show-played="!isContainerType && !isUnavailable"
            :show-instant-mix="!isContainerType && !isUnavailable"
            :show-refresh-metadata="authStore.isSuperuser"
            :is-favorited="isFavorited"
            :monitored="favoriteMonitored"
            :is-liked="isLiked"
            :is-played="isPlayed"
            :favorite-loading="togglingFavorite"
            :like-loading="togglingLiked"
            :played-loading="togglingPlayed"
            :instant-mix-loading="loadingInstantMix"
            :refresh-metadata-loading="refreshingMetadata"
            :play-loading="isSearching"
            :play-label="
              isUnavailable
                ? availability?.is_watched
                  ? $t('mediaDetail.watching')
                  : $t('mediaDetail.notifyWhenAvailable')
                : playButtonLabel
            "
            :play-icon="
              isUnavailable
                ? availability?.is_watched
                  ? 'mdi-bell-check'
                  : 'mdi-bell-outline'
                : 'mdi-play'
            "
            :play-color="
              isUnavailable ? (availability?.is_watched ? 'positive' : 'grey-7') : 'primary'
            "
            :play-outline="isUnavailable && !availability?.is_watched"
            @play="isUnavailable ? toggleWatch() : playMedia()"
            @add-to-list="addToList"
            @toggle-favorite="toggleFavorite"
            @toggle-like="toggleLike"
            @toggle-played="togglePlayed"
            @instant-mix="playInstantMix"
            @refresh-metadata="refreshMetadata"
          />
        </template>
      </MediaHeroSection>

      <!-- Media Content -->
      <div class="media-content q-px-xl q-pt-md">
        <div>
          <div>
            <!-- Description/Overview -->
            <div v-if="mediaItem.description" class="media-description">
              <h5 class="text-white q-mt-none q-mb-md">{{ $t('common.overview') }}</h5>
              <p class="text-grey-3 text-body1 line-height-lg">
                {{ mediaItem.description }}
              </p>
            </div>

            <MediaExternalLinks :links="externalLinks" />

            <!-- Type-specific sections -->
            <MediaChildrenSection
              :media-item="mediaItem"
              :children="children"
              :grouped-tracks="groupedTracks"
              :is-show="isShow"
              :is-season="isSeason"
              :is-artist="isArtist"
              :is-album="isAlbum"
              :is-multi-disc="isMultiDisc"
              :format-track-duration="formatTrackDuration"
              @view-child="viewChild"
              @play-episode="playEpisode"
              @play-track="playTrack"
            />

            <!-- Cast Section -->
            <MediaCastRow :cast-members="castMembers" />

            <!-- Similar items row (movies + shows) -->
            <SimilarMediaRow
              v-if="(isMovie || isShow) && mediaItem && mediaItem.guid"
              :item-guid="mediaItem.guid"
              :item-title="mediaItem.title"
            />

            <MediaAdminPanel
              v-if="authStore.isSuperuser && !isContainerType"
              :media-item="mediaItem"
              :files="files"
              :file-duration="fileDuration"
              :releases="releases"
              :downloads="downloads"
              :reprobing-files="reprobingFiles"
              :reprobing-file-id="reprobingFileId"
              :deleting-file-id="deletingFileId"
              :searching-releases="searchingReleases"
              :is-searching="isSearching"
              :downloading-release-id="downloadingReleaseId"
              :is-song="isSong"
              :is-game="isGame"
              @reprobe-all="reprobeAllFiles"
              @reprobe="reprobeFile"
              @delete-confirmed="deleteFile"
              @search="searchReleases"
              @download="downloadRelease"
              @delete-one="deleteRelease"
              @delete-all-confirmed="deleteAllReleases"
              @media-updated="loadMediaItem"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Dialog, useQuasar } from 'quasar'
import { useAuthStore } from 'stores/auth'
import { useAudioPlayerStore } from 'stores/audioPlayer'
import { useRemoteControlStore } from 'stores/remoteControl'
import { useMediaAdminActions } from 'src/composables/useMediaAdminActions'
import { useMediaAvailability } from 'src/composables/useMediaAvailability'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'
import { useMediaTypeFlags } from 'src/composables/useMediaTypeFlags'
import { useMediaCastPlayback } from 'src/composables/useMediaCastPlayback'
import { getTmdbImageUrl, getFileName, formatTime } from 'src/composables/useMediaFormatters'
import { useWebSocket } from 'src/composables/useWebSocket'
import { useFavorite } from 'src/composables/useFavorite'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'
import { MediaTypes } from 'src/composables/useUnifiedMedia'
import * as mediaService from 'src/services/mediaService'
import { logger } from 'src/utils/logger'

import MediaLoadingState from 'src/components/MediaLoadingState.vue'
import MediaErrorState from 'src/components/MediaErrorState.vue'
import MediaHeroSection from 'src/components/MediaHeroSection.vue'
import MediaActionButtons from 'src/components/MediaActionButtons.vue'
import MediaMetaChips from 'src/components/MediaMetaChips.vue'
import MediaAdminPanel from 'src/components/admin/MediaAdminPanel.vue'
import SimilarMediaRow from 'src/components/SimilarMediaRow.vue'
import MediaCastRow from 'src/components/MediaCastRow.vue'
import MediaChildrenSection from 'src/components/MediaChildrenSection.vue'
import MediaExternalLinks from 'src/components/MediaExternalLinks.vue'

export default {
  name: 'MediaDetailPage',
  components: {
    MediaLoadingState,
    MediaErrorState,
    MediaHeroSection,
    MediaActionButtons,
    MediaMetaChips,
    MediaAdminPanel,
    SimilarMediaRow,
    MediaCastRow,
    MediaChildrenSection,
    MediaExternalLinks,
  },
  setup() {
    const route = useRoute()
    const router = useRouter()
    const { t } = useI18n()
    const $q = useQuasar()
    const authStore = useAuthStore()
    const audioPlayerStore = useAudioPlayerStore()
    const remoteControlStore = useRemoteControlStore()
    const { subscribe, unsubscribe, onReconnected } = useWebSocket()
    const playbackTimers = useTimeoutRegistry()

    const {
      getPosterUrl,
      getBackdropUrl,
      formatYear,
      formatFullDate,
      formatRuntime,
      formatFileSize,
      formatDuration,
      formatGenres,
      getMediaStatus,
    } = useMediaHelpers()

    // State
    const loading = ref(true)
    const error = ref(null)
    const mediaItem = ref(null)
    const parentItem = ref(null) // Season item (for episodes)
    const showItem = ref(null) // Show item (for episodes/seasons)
    const files = ref([])
    const fileDuration = computed(() => files.value[0]?.duration || 0)
    const children = ref([]) // For shows: seasons; for series: episodes
    const releases = ref([])
    const externalLinks = ref([])
    const downloads = ref([])
    const playingMedia = ref(false) // Prevent double-play
    const isLiked = ref(false)
    const togglingLiked = ref(false)
    const isPlayed = ref(false)
    const togglingPlayed = ref(false)
    const loadingInstantMix = ref(false)

    // WebSocket handler for cleanup
    const websocketHandler = ref(null)
    const activeSubscriptionGuid = ref(null)

    // Monotonic token guarding loadMediaItem against out-of-order responses:
    // fast A->B navigation must not let A's slower fetch overwrite B's state.
    let currentLoadId = 0

    // Media type detection + boolean flags (shared with cast/playback routing)
    const {
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
    } = useMediaTypeFlags({ mediaItem, children })

    // Multi-disc album support
    const groupedTracks = computed(() => {
      const discs = {}
      for (const track of children.value) {
        let discNum = 1
        if (track.extra_data) {
          try {
            const data =
              typeof track.extra_data === 'string' ? JSON.parse(track.extra_data) : track.extra_data
            discNum = data?.disc_number || 1
          } catch (e) {
            // Malformed extra_data; default to disc 1
            logger.debug('Failed to parse track extra_data', e)
          }
        }
        if (!discs[discNum]) {
          discs[discNum] = { discNumber: discNum, tracks: [] }
        }
        discs[discNum].tracks.push(track)
      }
      return Object.values(discs).sort((a, b) => a.discNumber - b.discNumber)
    })
    const isMultiDisc = computed(() => groupedTracks.value.length > 1)

    // Episode-specific hero computed properties
    const heroTitle = computed(() => {
      if (isEpisode.value && showItem.value) {
        const showTitle = showItem.value.title || ''
        const sn = parentItem.value?.sequence_number ?? mediaItem.value?.season_number
        const en = mediaItem.value?.sequence_number ?? mediaItem.value?.episode_number
        const prefix = sn != null && en != null ? `S${sn}E${en}` : ''
        return prefix ? `${showTitle} · ${prefix}` : showTitle
      }
      // For seasons: show "SeriesName · SeasonTitle"
      if (isSeason.value && showItem.value) {
        return `${showItem.value.title} · ${mediaItem.value?.title || ''}`
      }
      // For albums: show "ArtistName · AlbumTitle"
      if (isAlbum.value && parentItem.value) {
        return `${parentItem.value.title} · ${mediaItem.value?.title || ''}`
      }
      // For songs: show "ArtistName · AlbumTitle · SongTitle"
      if (isSong.value && parentItem.value) {
        const albumTitle = parentItem.value.title || ''
        const artistTitle = showItem.value?.title || ''
        return artistTitle ? `${artistTitle} · ${albumTitle}` : albumTitle
      }
      return mediaItem.value?.title || ''
    })

    const heroPosterUrl = computed(() => {
      // For episodes/seasons: use show poster
      if ((isEpisode.value || isSeason.value) && showItem.value) return getPosterUrl(showItem.value)
      // For albums: use album poster (which is the Spotify album art)
      if (isAlbum.value) return getPosterUrl(mediaItem.value)
      // For songs: use parent album poster
      if (isSong.value && parentItem.value) return getPosterUrl(parentItem.value)
      return getPosterUrl(mediaItem.value)
    })

    const heroBackdropUrl = computed(() => {
      // For episodes: prefer still_path, then show backdrop
      if (isEpisode.value) {
        if (mediaItem.value?.still_path) {
          return getTmdbImageUrl(mediaItem.value.still_path, 'original')
        }
        if (showItem.value) return getBackdropUrl(showItem.value)
      }
      // For seasons: use show backdrop
      if (isSeason.value && showItem.value) return getBackdropUrl(showItem.value)
      // For albums/songs: use album poster as backdrop (music rarely has separate backdrops)
      if (isAlbum.value) return getPosterUrl(mediaItem.value)
      if (isSong.value && parentItem.value) return getPosterUrl(parentItem.value)
      return getBackdropUrl(mediaItem.value)
    })

    // Cast / remote-target playback routing (shares the type flags + hero refs)
    const {
      playSelectedRemoteTarget,
      playSelectedRemoteQueue,
      playSelectedRemoteInstantMix,
      getPlayType,
      getPlayTypeForItem,
      trackToPlayerTrack,
    } = useMediaCastPlayback({
      mediaItem,
      files,
      parentItem,
      heroTitle,
      heroPosterUrl,
      mediaType,
      isMovie,
      isShow,
      isEpisode,
      isGame,
      isSong,
      isMusicType,
      remoteControlStore,
      getPosterUrl,
    })

    // Dynamic labels and routes based on media type
    const backRoute = computed(() => {
      // If item has a parent, navigate to the parent detail page
      if (mediaItem.value?.parent_guid) {
        return `/media/${mediaItem.value.parent_guid}`
      }

      // Navigate to the library list page by media type
      if (mediaType.value) {
        // Map media sub-types to their library type
        const typeMap = {
          MOVIES: 'movies',
          SHOWS: 'shows',
          GAMES: 'games',
          MUSIC: 'music',
          ARTISTS: 'music',
          ALBUMS: 'music',
          SONGS: 'music',
          BOOKS: 'books',
        }
        const libraryType = typeMap[mediaType.value] || mediaType.value.toLowerCase()
        return `/${libraryType}`
      }

      return '/'
    })

    const backLabel = computed(() => t(`${mediaType.value}.backToList`))

    const PLACEHOLDER_ICONS = {
      [MediaTypes.MOVIES]: 'mdi-movie',
      [MediaTypes.SERIES]: 'mdi-television',
      [MediaTypes.GAMES]: 'mdi-controller',
      [MediaTypes.MUSIC]: 'mdi-music',
      [MediaTypes.ALBUMS]: 'mdi-music',
      [MediaTypes.SONGS]: 'mdi-music',
      [MediaTypes.ARTISTS]: 'mdi-account-music',
      [MediaTypes.BOOKS]: 'mdi-book',
    }
    const placeholderIcon = computed(() => PLACEHOLDER_ICONS[mediaType.value] || 'mdi-file')

    const placeholderText = computed(() => t(`${mediaType.value}.noPosterAvailable`))

    const playButtonLabel = computed(() => {
      if (isGame.value) return t('common.playGame')
      if (isBook.value) return t('common.read')
      if (isMusic.value || isArtist.value || isAlbum.value || isSong.value)
        return t('common.listen')
      return t('common.watch')
    })

    // Media metadata computed properties
    const mediaYear = computed(() => {
      if (!mediaItem.value) return null
      return formatYear(mediaItem.value.release_date)
    })

    const mediaStatus = computed(() => {
      if (!mediaItem.value) return null
      if (isMovie.value) return getMediaStatus(mediaItem.value.release_date)
      if (isShow.value) return mediaItem.value.status
      return null
    })

    const mediaStatusLabel = computed(() => {
      const status = mediaStatus.value
      if (!status) return null
      return t(`status.${status}`)
    })

    const STATUS_COLORS = {
      released: 'positive',
      'Returning Series': 'positive',
      Ended: 'negative',
    }
    const mediaStatusColor = computed(
      () => STATUS_COLORS[mediaStatus.value] || (mediaStatus.value ? 'orange' : 'grey'),
    )

    const hasPlayableContent = computed(() => {
      // Games always playable via Lightrays cloud streaming
      if (isGame.value) return true
      // Use availability endpoint result when available
      if (availability.value) {
        return (
          availability.value.status === 'available' ||
          availability.value.status === 'downloadable' ||
          availability.value.status === 'downloading' ||
          availability.value.status === 'searching'
        )
      }
      // Fallback: check local data (before availability loads)
      if (files.value.length > 0 || releases.value.length > 0) return true
      return false
    })

    const isUnavailable = computed(() => {
      return availability.value?.status === 'unavailable'
    })

    const isSearching = computed(() => {
      return availability.value?.status === 'searching'
    })

    // Cast members (actors and crew)
    const castMembers = computed(() => {
      if (!mediaItem.value?.cast) return []
      return mediaItem.value.cast
    })

    const {
      availability,
      refreshAvailability,
      toggleWatch,
      clearAvailabilityTimers,
      unsubscribeAvailabilityTarget,
    } = useMediaAvailability({
      mediaItem,
      subscribe,
      unsubscribe,
      getWebSocketHandler: () => websocketHandler.value,
    })

    const {
      refreshingMetadata,
      searchingReleases,
      reprobingFiles,
      reprobingFileId,
      deletingFileId,
      downloadingReleaseId,
      loadReleasesData,
      loadDownloadsData,
      handleFilesUpdated,
      searchReleases,
      downloadRelease,
      deleteRelease,
      deleteAllReleases,
      reprobeFile,
      reprobeAllFiles,
      deleteFile,
      refreshMetadata,
      clearAdminTimers,
    } = useMediaAdminActions({
      mediaItem,
      files,
      releases,
      downloads,
      loadMediaItem,
      isSuperuser: computed(() => authStore.isSuperuser),
    })

    // Load media item with all related data
    async function loadMediaItem() {
      const guid = route.params.guid
      if (!guid) {
        error.value = t('common.noIdProvided')
        return
      }

      // Claim this invocation's token; any later loadMediaItem() supersedes it.
      const loadId = ++currentLoadId
      const isStale = () => loadId !== currentLoadId

      loading.value = true
      error.value = null
      children.value = []
      parentItem.value = null
      showItem.value = null
      clearAdminTimers()
      clearAvailabilityTimers()
      if (activeSubscriptionGuid.value && websocketHandler.value) {
        unsubscribeAvailabilityTarget(activeSubscriptionGuid.value)
        unsubscribe('media_item', activeSubscriptionGuid.value, websocketHandler.value)
        activeSubscriptionGuid.value = null
        websocketHandler.value = null
      }

      try {
        // Subscribe to WebSocket events BEFORE fetching, so we don't miss
        // events triggered by the fetch (e.g. background release search)
        websocketHandler.value = async (event, data) => {
          logger.debug('[MediaDetail] WebSocket event:', event, data)
          if (event === 'releases_updated') {
            handleReleasesUpdated(data)
            refreshAvailability()
          } else if (event === 'files_updated' || event === 'media_available') {
            handleFilesUpdated(data)
            refreshAvailability()
          } else if (event === 'download_updated') {
            loadDownloadsData()
            refreshAvailability()
          }
        }

        subscribe('media_item', guid, websocketHandler.value)
        activeSubscriptionGuid.value = String(guid)
        logger.debug('[MediaDetail] Subscribed to media_item:', guid)

        // Load media item with files and releases
        const data = await mediaService.loadMediaItem(guid, {
          load_files: true,
          load_releases: true,
          load_external_ids: true,
        })
        // A newer navigation started while this fetch was in flight; drop it so
        // its data can't overwrite the item the URL now points at.
        if (isStale()) return

        mediaItem.value = data
        files.value = data.files || []
        releases.value = data.releases || []
        externalLinks.value = data.external_links || []

        // Shows contain seasons; explicit SEASONS items contain episodes.
        // Older databases represented both levels as SHOWS, hence the fallback.
        if (data.media_type === 'SHOWS' || data.media_type === 'SEASONS') {
          const childrenData = await mediaService.loadMediaChildren(guid, true)
          if (isStale()) return
          children.value = childrenData || []
          logger.debug(
            'Loaded children:',
            children.value.length,
            'for',
            data.parent_guid ? 'season' : 'show',
          )
        }

        // For artists, load albums; for albums, load tracks
        if (data.media_type === 'ARTISTS' || data.media_type === 'ALBUMS') {
          const childrenData = await mediaService.loadMediaChildren(guid, true)
          if (isStale()) return
          children.value = childrenData || []
          logger.debug(
            'Loaded children:',
            children.value.length,
            'for',
            data.media_type === 'ARTISTS' ? 'artist' : 'album',
          )
        }

        // For episodes/seasons: load parent hierarchy
        if (data.parent_guid) {
          try {
            const parent = await mediaService.loadMediaItem(data.parent_guid, {
              load_files: false,
              load_releases: false,
              load_external_ids: false,
            })
            if (isStale()) return
            parentItem.value = parent
            // If parent itself has a parent (episode -> season -> show)
            if (parent.parent_guid) {
              const show = await mediaService.loadMediaItem(parent.parent_guid, {
                load_files: false,
                load_releases: false,
                load_external_ids: false,
              })
              if (isStale()) return
              showItem.value = show
            } else {
              // parent IS the show
              showItem.value = parent
            }
          } catch (e) {
            logger.warn('[MediaDetail] Could not load parent hierarchy:', e)
          }
        }

        // Fetch availability (triggers auto-search, determines playability)
        await refreshAvailability()
        if (isStale()) return

        // Check favorite status
        await checkFavoriteStatus()
        if (isStale()) return
        await loadUserDataStatus()
        if (isStale()) return

        // Load downloads for admin
        await loadDownloadsData()
      } catch (err) {
        if (isStale()) return
        logger.error('Error loading media item:', err)
        error.value = t('common.failedToLoadDetails')
      } finally {
        // Only the most recent invocation owns the shared loading flag.
        if (!isStale()) loading.value = false
      }
    }

    // Play media
    async function playMedia() {
      if (!mediaItem.value) return

      // Prevent double-execution
      if (playingMedia.value) {
        logger.warn('playMedia already in progress, ignoring duplicate call')
        return
      }

      playingMedia.value = true

      try {
        // For shows and seasons, use availability target
        if ((isShow.value || isSeason.value) && availability.value?.target_guid) {
          if (await playSelectedRemoteTarget(availability.value.target_guid, 'episode')) {
            return
          }
          router.push(`/play/${availability.value.target_guid}?type=episode`)
          return
        }

        // For albums, play all tracks in the audio player
        if (isAlbum.value && children.value.length > 0) {
          if (await playSelectedRemoteQueue(children.value.map((track) => track.guid))) {
            return
          }
          const tracks = children.value.map(trackToPlayerTrack)
          audioPlayerStore.playAlbum(tracks)
          return
        }

        // For songs, play in the audio player
        if (isSong.value) {
          if (await playSelectedRemoteTarget(mediaItem.value.guid, 'music')) {
            return
          }
          audioPlayerStore.play(trackToPlayerTrack(mediaItem.value))
          return
        }

        // Check if only low-quality releases are available and warn the user
        const hasReleases = releases.value.length > 0
        const allLowQuality =
          hasReleases && releases.value.every((r) => r.release_metadata?.is_low_quality === true)

        if (allLowQuality) {
          const proceed = await new Promise((resolve) => {
            Dialog.create({
              title: t('common.lowQualityWarningTitle'),
              message: t('common.lowQualityWarningMessage'),
              cancel: true,
              persistent: true,
              ok: { label: t('common.playAnyway'), color: 'warning' },
            })
              .onOk(() => resolve(true))
              .onCancel(() => resolve(false))
          })
          if (!proceed) return
        }

        // Navigate directly to play page - PlayPage handles all states (streaming, downloading, etc.)
        if (await playSelectedRemoteTarget(mediaItem.value.guid, getPlayType())) {
          return
        }
        router.push(`/play/${mediaItem.value.guid}?type=${getPlayType()}`)
      } catch (err) {
        logger.error('Error starting playback:', err)
      } finally {
        // Reset flag after a short delay to allow navigation
        playbackTimers.schedule(() => {
          playingMedia.value = false
        }, 1000)
      }
    }

    // View child item (season for shows, episode for seasons, album for artists, song for albums)
    function viewChild(child) {
      if (!child || !mediaItem.value) return
      router.push(`/media/${child.guid}`)
    }

    async function playInstantMix() {
      if (!mediaItem.value?.guid || isContainerType.value) return
      loadingInstantMix.value = true
      try {
        const data = await mediaService.getInstantMix(mediaItem.value.guid)
        const items = data?.items || []
        if (items.length === 0) return
        const itemIds = items.map((item) => item.guid).filter(Boolean)

        if (await playSelectedRemoteInstantMix(itemIds)) {
          return
        }

        if (isSong.value || isAlbum.value || isArtist.value || isMusic.value) {
          const tracks = items.map(trackToPlayerTrack)
          await audioPlayerStore.playAlbum(tracks)
          return
        }

        const first = items[0]
        if (first?.guid) {
          router.push(`/play/${first.guid}?type=${getPlayTypeForItem(first)}`)
        }
      } catch (err) {
        logger.error('Error starting instant mix:', err)
      } finally {
        loadingInstantMix.value = false
      }
    }

    // Play a single track from the album track list
    async function playTrack(track) {
      if (await playSelectedRemoteTarget(track.guid, 'music')) {
        return
      }
      const allTracks = children.value.map(trackToPlayerTrack)
      const playerTrack = trackToPlayerTrack(track)
      audioPlayerStore.play(playerTrack, allTracks)
    }

    // Play episode directly
    async function playEpisode(episode) {
      if (!episode) return

      try {
        if (await playSelectedRemoteTarget(episode.guid, 'episode')) {
          return
        }
        // Navigate directly to play page - PlayPage handles all states (streaming, downloading, etc.)
        router.push(`/play/${episode.guid}?type=episode`)
      } catch (err) {
        logger.error('Error starting episode playback:', err)
      }
    }

    // Add to list
    async function addToList() {
      if (!mediaItem.value) return
      const { default: AddToListDialog } = await import('src/components/AddToListDialog.vue')
      $q.dialog({
        component: AddToListDialog,
        componentProps: {
          mediaTitle: mediaItem.value.title || '',
          mediaGuid: mediaItem.value.guid,
          mediaType: mediaItem.value.media_type,
        },
      }).onOk(() => {})
    }

    // Resolve the GUID and type prefix to use for favoriting.
    // Seasons and episodes always favorite their top-level show.
    const FAVORITE_TYPE_PREFIX = {
      [MediaTypes.MOVIES]: 'movies',
      [MediaTypes.SERIES]: 'shows',
      [MediaTypes.GAMES]: 'games',
      [MediaTypes.MUSIC]: 'music',
      [MediaTypes.ARTISTS]: 'music',
      [MediaTypes.ALBUMS]: 'music',
      [MediaTypes.SONGS]: 'music',
      [MediaTypes.BOOKS]: 'books',
    }
    function getFavoriteTarget() {
      if (isSeason.value || isEpisode.value) {
        // Walk up to the show: prefer loaded showItem, fall back to parent_guid.
        const showGuid =
          showItem.value?.guid || (isSeason.value ? mediaItem.value?.parent_guid : null)
        return { typePrefix: 'shows', guid: showGuid || mediaItem.value?.guid }
      }
      return {
        typePrefix: FAVORITE_TYPE_PREFIX[mediaType.value] || 'movies',
        guid: mediaItem.value?.guid,
      }
    }

    const {
      isFavorited,
      monitored: favoriteMonitored,
      toggling: togglingFavorite,
      checkStatus: checkFavoriteStatus,
      toggle: toggleFavorite,
    } = useFavorite(getFavoriteTarget)

    async function loadUserDataStatus() {
      if (!mediaItem.value?.guid || isContainerType.value) {
        isLiked.value = false
        isPlayed.value = false
        return
      }
      try {
        const data = await mediaService.getMediaUserData(mediaItem.value.guid)
        isLiked.value = Boolean(data?.is_liked)
        isPlayed.value = Boolean(data?.is_played)
      } catch (err) {
        logger.debug('[MediaDetail] Could not load user data:', err)
      }
    }

    async function toggleLike() {
      if (!mediaItem.value?.guid || isContainerType.value) return
      togglingLiked.value = true
      try {
        const data = await mediaService.setMediaLike(mediaItem.value.guid, isLiked.value)
        isLiked.value = Boolean(data?.is_liked)
      } catch (err) {
        logger.error('Error toggling like state:', err)
        $q.notify({ type: 'negative', message: t('common.actionFailed') })
      } finally {
        togglingLiked.value = false
      }
    }

    async function togglePlayed() {
      if (!mediaItem.value?.guid || isContainerType.value) return
      togglingPlayed.value = true
      try {
        const data = await mediaService.setMediaPlayed(mediaItem.value.guid, isPlayed.value)
        isPlayed.value = Boolean(data?.is_played)
      } catch (err) {
        logger.error('Error toggling played state:', err)
        $q.notify({ type: 'negative', message: t('common.actionFailed') })
      } finally {
        togglingPlayed.value = false
      }
    }

    // Helper functions
    function getStatusColor(status) {
      return STATUS_COLORS[status] || 'info'
    }

    // Format track duration from milliseconds (from Spotify extra_data)
    function formatTrackDuration(item) {
      if (!item?.extra_data) return null
      try {
        const data =
          typeof item.extra_data === 'string' ? JSON.parse(item.extra_data) : item.extra_data
        const ms = data?.duration_ms
        return ms ? formatTime(Math.floor(ms / 1000)) : null
      } catch (e) {
        // Malformed extra_data; treat duration as unknown
        logger.debug('Failed to parse item extra_data', e)
        return null
      }
    }

    // WebSocket event handlers
    function handleReleasesUpdated(data) {
      logger.debug('[MediaDetail] Releases updated:', data)

      // Search finished — stop loading indicator
      searchingReleases.value = false

      // Reload releases
      if (mediaItem.value) {
        loadReleasesData()
        loadDownloadsData()
      }
    }

    // Re-fetch availability + files after WS reconnects so events missed
    // during the disconnect gap don't leave this page showing stale state.
    const stopReconnectListener = onReconnected(() => {
      if (mediaItem.value) {
        refreshAvailability()
      }
    })

    // Cleanup on unmount
    onUnmounted(() => {
      stopReconnectListener()
      if (activeSubscriptionGuid.value && websocketHandler.value) {
        unsubscribeAvailabilityTarget(activeSubscriptionGuid.value)
        unsubscribe('media_item', activeSubscriptionGuid.value, websocketHandler.value)
        logger.debug('[MediaDetail] Unsubscribed from media_item:', activeSubscriptionGuid.value)
      }
    })

    // Watch route changes to reload
    watch(
      () => route.params.guid,
      (newGuid) => {
        if (newGuid) {
          loadMediaItem()
        }
      },
      { immediate: true },
    )

    return {
      loading,
      error,
      mediaItem,
      files,
      fileDuration,
      children,
      releases,
      externalLinks,
      isLiked,
      togglingLiked,
      isPlayed,
      togglingPlayed,
      loadingInstantMix,
      isFavorited,
      favoriteMonitored,
      togglingFavorite,
      refreshingMetadata,
      searchingReleases,
      authStore,
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
      parentItem,
      showItem,
      heroTitle,
      heroPosterUrl,
      heroBackdropUrl,
      backRoute,
      backLabel,
      placeholderIcon,
      placeholderText,
      playButtonLabel,
      mediaYear,
      mediaStatus,
      mediaStatusLabel,
      mediaStatusColor,
      hasPlayableContent,
      isUnavailable,
      isSearching,
      availability,
      toggleWatch,
      castMembers,
      getPosterUrl,
      getBackdropUrl,
      formatYear,
      formatFullDate,
      formatRuntime,
      formatFileSize,
      formatDuration,
      formatGenres,
      getStatusColor,
      getFileName,
      downloads,
      reprobingFiles,
      reprobingFileId,
      deletingFileId,
      downloadingReleaseId,
      playMedia,
      playEpisode,
      viewChild,
      playTrack,
      searchReleases,
      downloadRelease,
      deleteRelease,
      deleteAllReleases,
      loadDownloadsData,
      reprobeFile,
      reprobeAllFiles,
      deleteFile,
      refreshMetadata,
      addToList,
      toggleFavorite,
      toggleLike,
      togglePlayed,
      playInstantMix,
      formatTrackDuration,
      groupedTracks,
      isMultiDisc,
      getTmdbImageUrl,
    }
  },
}
</script>

<style lang="scss" scoped>
.language-flags {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.lang-flag {
  font-size: 1.2rem;
  cursor: default;
}
.blacklisted-row {
  opacity: 0.6;
}
.media-detail-page {
  min-height: 100vh;
  background: $dark;
}

.media-content {
  max-width: 1400px;
  margin: 0 auto;
}

.media-description {
  .line-height-lg {
    line-height: 1.8;
  }
}

// Cast section, season-card, episode-* styles live in MediaCastRow,
// MediaChildCard and EpisodeListItem components.

.meta-item {
  margin-bottom: 1rem;

  &:last-child {
    margin-bottom: 0;
  }
}

@media (max-width: 1024px) {
  .media-content {
    padding-left: 20px !important;
    padding-right: 20px !important;
  }
}
</style>
