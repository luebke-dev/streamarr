<template>
  <q-page class="play-page">
    <!-- Status screens: loading, downloading, error, no-release -->
    <PlayStatusScreen
      v-if="loading || status === 'downloading' || status === 'error' || status === 'no-release'"
      :loading="loading"
      :status="status"
      :content-info="contentInfo"
      :content-type="contentType"
      :download-progress="downloadProgress"
      :download-status="downloadStatus"
      :download-phase="downloadPhase"
      :error-message="errorMessage"
      @back="goBack"
      @retry="checkContent"
      @search-releases="searchReleases"
    />

    <!-- Book Reader -->
    <BookReader
      v-else-if="status === 'book-reading'"
      :file-url="bookFileUrl"
      :format="bookFormat"
      :file-name="bookFileName"
      :media-guid="uuid"
    />

    <!-- Game Streaming via Lightrays -->
    <GameStreamView
      v-else-if="status === 'game-streaming'"
      :session-id="gameSessionId"
      :ws-ticket="wsTicket"
      :websocket-url="websocketUrl"
      :ice-servers="gameIceServers"
      :game-title="contentTitle"
      @back="goBack"
      @retry="checkContent"
      @disconnected="goBack"
    />

    <!-- Video Player with Custom Controls (when streamable) -->
    <div ref="playerWrapperRef" v-else-if="status === 'streamable'" class="player-wrapper">
      <video-player
        class="video-container"
        :src="videoSrc"
        :controls="false"
        :liveui="false"
        autoplay="play"
        :loop="false"
        :volume="0.6"
        @mounted="onPlayerMounted"
        @ready="onPlayerReady"
        @timeupdate="onTimeUpdate"
        @ended="onVideoEnded"
        @pause="onVideoPause"
      />

      <!-- Custom Player Controls Overlay -->
      <CustomPlayerControls
        :player-state="playerControlState"
        :media-state="mediaControlState"
        :navigation-state="navigationControlState"
        :stream-state="streamControlState"
        @seek="handleSeek"
        @change-audio-track="handleAudioTrackChange"
        @toggle-play="togglePlayPause"
        @toggle-mute="toggleMute"
        @volume-change="setVolume"
        @toggle-fullscreen="toggleFullscreen"
        @back="goBack"
        @next-episode="playNextPlaybackItem"
        @previous-episode="playPreviousPlaybackItem"
        @toggle-favorite="toggleFavorite"
        @select-quality="handleQualityChange"
        @identify-song="handleIdentifySong"
        @report-problem="showReportDialog = true"
      />

      <!-- Report Problem Dialog -->
      <ReportProblemDialog v-model="showReportDialog" :media-uuid="uuid" @submitted="goBack" />

      <!-- Skip Intro/Outro Overlays -->
      <SkipOverlay
        :visible="showSkipIntro"
        :label="$t('player.skipIntro')"
        @skip="skipToPosition(activeIntroMarker?.end)"
      />
      <SkipOverlay
        :visible="showSkipOutro || showSkipCredits"
        :label="showSkipCredits ? $t('player.skipCredits') : $t('player.skipOutro')"
        @skip="skipToPosition(showSkipCredits ? videoDuration : markers?.outro_end)"
      />

      <!-- Song Identification Result -->
      <IdentifySongDialog v-model="showSongDialog" :song="identifiedSong" :error="songError" />
    </div>
  </q-page>
</template>

<script setup>
import { computed, defineAsyncComponent, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from 'stores/auth'
import { useWebSocket } from 'src/composables/useWebSocket'
import { useFavorite } from 'src/composables/useFavorite'
import { useOfflineStore } from 'stores/offline'
import { useRemoteControlStore } from 'stores/remoteControl'
import { usePartyStore } from 'stores/party'
import { usePartyWebSocket } from 'src/composables/usePartyWebSocket'
import {
  startPlayback as startUnifiedPlayback,
  getDirectFileUrl,
  getPlaylistUrl,
  stopStreaming,
} from 'src/composables/usePlay'
import { logger } from 'src/utils/logger'
import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'
import { useDownloadPolling } from 'src/composables/useDownloadPolling'
import { useViewingProgress } from 'src/composables/useViewingProgress'
import { useStreamSwap } from 'src/composables/useStreamSwap'
import { useVideoPlayerEvents } from 'src/composables/useVideoPlayerEvents'
import { useBookPlayback } from 'src/composables/useBookPlayback'
import { usePlayerControls } from 'src/composables/usePlayerControls'
import { useGameLaunch } from 'src/composables/useGameLaunch'
import { useEpisodeNavigation } from 'src/composables/useEpisodeNavigation'
import { usePlaylistNavigation } from 'src/composables/usePlaylistNavigation'
import { usePlaybackBootstrap } from 'src/composables/usePlaybackBootstrap'
import { useSongIdentification } from 'src/composables/useSongIdentification'
import { useSkipMarkers } from 'src/composables/useSkipMarkers'
import { useMediaSession } from 'src/composables/useMediaSession'
import { useRemoteControlReceiver } from 'src/composables/useRemoteControlReceiver'
import { usePartySync } from 'src/composables/usePartySync'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'
import { useStreamReadiness } from 'src/composables/useStreamReadiness'
import * as mediaService from 'src/services/mediaService'
import { getServerUrl } from 'src/utils/authStorage'
import 'video.js/dist/video-js.css'

const VideoPlayer = defineAsyncComponent(() =>
  import('@videojs-player/vue').then((module) => module.VideoPlayer),
)
const CustomPlayerControls = defineAsyncComponent(() => import('components/CustomPlayerControls.vue'))
const SkipOverlay = defineAsyncComponent(() => import('components/SkipOverlay.vue'))
const GameStreamView = defineAsyncComponent(() => import('components/GameStreamView.vue'))
const BookReader = defineAsyncComponent(() => import('components/BookReader.vue'))
const PlayStatusScreen = defineAsyncComponent(() => import('components/PlayStatusScreen.vue'))
const ReportProblemDialog = defineAsyncComponent(() => import('components/ReportProblemDialog.vue'))
const IdentifySongDialog = defineAsyncComponent(() => import('components/IdentifySongDialog.vue'))

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const wsStore = useWebSocket()
const offlineStore = useOfflineStore()
const remoteControlStore = useRemoteControlStore()
const partyStore = usePartyStore()
const partyWs = usePartyWebSocket()
const playbackTimers = useTimeoutRegistry()
const { waitForHlsStreamReady } = useStreamReadiness()

// State
const loading = ref(true)
const status = ref('') // 'streamable', 'downloading', 'no-release', 'error'
const errorMessage = ref('')
const contentInfo = ref(null)
const duration = ref(0)
const videoDuration = ref(0)
const isStartingPlayback = ref(false) // Guard against duplicate startPlayback calls
let playbackGuardTimer = null

// Custom controls state
const transcodeStartPosition = ref(0) // Position where current transcode started
const streamPosition = ref(0) // Current position within the stream
const bufferedAmount = ref(0)
const isSeeking = ref(false)
const currentAudioTrackIndex = ref(null) // Currently selected audio track index
const currentMediaSourceId = ref(null) // Currently selected MediaFile GUID
const savedTrackPreferences = ref(null)
const isPlaying = ref(false)
const videoElement = ref(null)
const videoJsPlayer = ref(null)
const playerState = ref(null)
const {
  isFavorited,
  checkStatus: loadFavoriteStatus,
  toggle: toggleFavorite,
} = useFavorite(() => {
  if (!uuid.value) return null
  const typePrefix = contentType.value === 'episode' ? 'shows' : 'movies'
  // For episodes: use show_guid (grandparent) — parent_guid points to the season, not the show
  const guidToUse =
    contentType.value === 'episode' ? contentInfo.value?.show_guid || uuid.value : uuid.value
  return { typePrefix, guid: guidToUse }
})
const markers = ref(null) // { intro_start, intro_end, outro_start, outro_end, credits_start, credits_end }
const playbackPrefs = ref(null) // { skip_intro_mode, skip_outro_mode, skip_credits_mode }

const { activeIntroMarker, showSkipIntro, showSkipOutro, showSkipCredits, skipToPosition } =
  useSkipMarkers({
    markers,
    playbackPrefs,
    transcodeStartPosition,
    streamPosition,
    videoDuration,
    onSkip: (seconds) => handleSeek(seconds),
  })
const playerWrapperRef = ref(null)

// Report problem
const showReportDialog = ref(false)

// Download status
const playToken = ref('') // Play token for accessing stream
const sessionId = ref('') // Unified streaming session ID
const directStreamUrl = ref('')
const streamInfo = ref(null) // Stream info for admin debug panel
const offlineObjectMediaGuid = ref('')
const playbackTargetOptions = ref({})

const uuid = computed(() => {
  return route.params.id || route.params.guid || ''
})
const contentType = computed(() => route.query.type || 'movie') // 'movie' or 'episode'
const playlistId = computed(() => route.query.playlist || route.query.playlist_id || '')
const playlistIndex = computed(() => {
  const parsed = Number.parseInt(route.query.playlist_index || '0', 10)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
})

const { gameSessionId, wsTicket, websocketUrl, gameIceServers, launchGameStream } = useGameLaunch({
  uuid,
  status,
  loading,
  errorMessage,
  t,
})

const { bookFileUrl, bookFormat, bookFileName, openBookFile } = useBookPlayback({
  status,
  loading,
})

const { identifyingSong, identifiedSong, showSongDialog, songError, handleIdentifySong } =
  useSongIdentification({
    uuid,
    transcodeStartPosition,
    streamPosition,
    t,
  })

function numericRouteQuery(name) {
  const value = Array.isArray(route.query[name]) ? route.query[name][0] : route.query[name]
  if (value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stringRouteQuery(name) {
  const value = Array.isArray(route.query[name]) ? route.query[name][0] : route.query[name]
  return value ? String(value) : ''
}

// Download polling (composable owns interval + ws subscription).
// onAvailable is wrapped to forward-reference startPlayback (defined below).
const {
  downloadProgress,
  downloadStatus,
  downloadPhase,
  setDownloadState,
  start: startDownloadPolling,
  stop: stopDownloadPolling,
  reset: resetDownloadProgress,
} = useDownloadPolling({
  uuid,
  status,
  loading,
  videoDuration,
  onAvailable: () => startPlayback(),
})

const {
  hasPreviousEpisode,
  hasNextEpisode,
  previousEpisodeData,
  nextEpisodeData,
  checkEpisodeNavigation,
  playPreviousEpisode,
  playNextEpisode,
  resetEpisodeNavigation,
} = useEpisodeNavigation({ uuid, contentType, router })

const {
  resetPlaylistNavigation,
  checkPlaylistNavigation,
  showPlaybackNavigation,
  hasPreviousPlaybackItem,
  hasNextPlaybackItem,
  previousPlaybackItemData,
  nextPlaybackItemData,
  playPreviousPlaybackItem,
  playNextPlaybackItem,
} = usePlaylistNavigation({
  playlistId,
  playlistIndex,
  contentType,
  router,
  episodeNavigation: {
    hasPreviousEpisode,
    hasNextEpisode,
    previousEpisodeData,
    nextEpisodeData,
    playPreviousEpisode,
    playNextEpisode,
  },
})

const contentTitle = computed(() => {
  if (!contentInfo.value) return ''
  if (contentType.value === 'episode') {
    const showTitle = contentInfo.value.show_title || ''
    const s = contentInfo.value.season_number
    const e = contentInfo.value.episode_number
    return `${showTitle} · S${s}E${e}`
  }
  return contentInfo.value.title || contentInfo.value.name || ''
})

const contentSubtitle = computed(() => {
  if (!contentInfo.value || contentType.value !== 'episode') return ''
  // For episodes, just return the episode title
  return contentInfo.value.title || ''
})

const playerControlState = computed(() => ({
  videoElement: videoElement.value,
  player: videoJsPlayer.value,
  totalDuration: videoDuration.value,
  transcodeStartPosition: transcodeStartPosition.value,
  streamPosition: streamPosition.value,
  bufferedAmount: bufferedAmount.value,
  isSeeking: isSeeking.value,
  isPlaying: isPlaying.value,
}))

const mediaControlState = computed(() => ({
  contentId: uuid.value,
  contentType: contentType.value,
  title: contentTitle.value,
  subtitle: contentSubtitle.value,
  isFavorited: isFavorited.value,
  identifyingLoading: identifyingSong.value,
}))

const navigationControlState = computed(() => ({
  showEpisodeControls: showPlaybackNavigation.value,
  hasPreviousEpisode: hasPreviousPlaybackItem.value,
  hasNextEpisode: hasNextPlaybackItem.value,
  previousEpisodeData: previousPlaybackItemData.value,
  nextEpisodeData: nextPlaybackItemData.value,
}))

const streamControlState = computed(() => ({
  streamInfo: streamInfo.value,
}))

const videoSrc = computed(() => {
  if (directStreamUrl.value) {
    return directStreamUrl.value
  }
  if (uuid.value && status.value === 'streamable' && playToken.value && sessionId.value) {
    // Use unified streaming API with session ID and play token
    return getPlaylistUrl(sessionId.value, playToken.value)
  }
  return ''
})

// Load auto-skip preferences (intro/outro/credits) once per session.
const loadPlaybackPreferences = async () => {
  if (playbackPrefs.value) return
  try {
    playbackPrefs.value = await authStore.fetchPlaybackPreferences()
  } catch (e) {
    logger.warn('Failed to load playback preferences, using defaults', e)
    playbackPrefs.value = {
      skip_intro_mode: 'button',
      skip_outro_mode: 'button',
      skip_credits_mode: 'button',
    }
  }
}

const loadSavedTrackPreferences = async () => {
  if (savedTrackPreferences.value || !uuid.value) return
  try {
    savedTrackPreferences.value = await mediaService.getMediaUserData(uuid.value)
  } catch (error) {
    logger.debug('Failed to load saved track preferences:', error)
    savedTrackPreferences.value = {}
  }
}

const resolveDirectStreamUrl = (url, token, directPlay) => {
  if (url?.startsWith('blob:') || url?.startsWith('http://') || url?.startsWith('https://')) {
    return url
  }
  if (url) return `${getServerUrl(window.location.origin)}${url}`
  return directPlay && token ? getDirectFileUrl(token) : ''
}

// Set up state for a streamable response and wait for the stream to be ready.
const setupStreamablePlayback = async (playResponse) => {
  videoDuration.value = playResponse.duration || 0
  playToken.value = playResponse.token || ''
  sessionId.value = playResponse.session_id || ''
  directStreamUrl.value = resolveDirectStreamUrl(
    playResponse.direct_file_url,
    playResponse.token,
    playResponse.direct_play,
  )
  transcodeStartPosition.value = playResponse.start_position || 0
  streamPosition.value = 0
  streamInfo.value = playResponse.stream_info || null
  markers.value = playResponse.markers || null
  playbackTargetOptions.value = {
    ...(playResponse.profile_id ? { profile_id: playResponse.profile_id } : {}),
    ...(playResponse.device_guid ? { device_guid: playResponse.device_guid } : {}),
  }
  currentMediaSourceId.value =
    playResponse.media_source_id || playResponse.stream_info?.source_file?.file_guid || null

  await loadPlaybackPreferences()

  // Persist audio track selected by backend so seeks reuse it
  if (playResponse.audio_track != null) {
    currentAudioTrackIndex.value = playResponse.audio_track
  }

  const streamReady = directStreamUrl.value
    ? true
    : await waitForHlsStreamReady(sessionId.value, playToken.value)
  if (!streamReady) {
    loading.value = false
    return
  }

  status.value = 'streamable'
  loading.value = false
  lastPosition.value = 0
}

const prefersOfflinePlayback = () => {
  const requested = String(route.query.offline || '').toLowerCase()
  return ['1', 'true', 'yes'].includes(requested) || navigator.onLine === false
}

const tryOfflinePlayback = async () => {
  if (!prefersOfflinePlayback()) return null

  try {
    const offlineEntry = await offlineStore.createObjectUrlForMedia(uuid.value)
    if (!offlineEntry?.url) return null
    offlineObjectMediaGuid.value = uuid.value
    const item = offlineEntry.item || {}
    return {
      status: 'ready',
      direct_play: true,
      direct_file_url: offlineEntry.url,
      duration: item.duration || contentInfo.value?.duration || 0,
      media_source_id: item.file_guid || null,
      message: 'Ready to play from offline manifest',
      stream_info: {
        source: 'offline_manifest',
        source_file: {
          file_guid: item.file_guid || null,
          file_name: item.file_name || null,
          file_size: item.file_size || null,
        },
      },
    }
  } catch (error) {
    logger.warn('[Offline] Offline playback unavailable, falling back to streaming:', error)
    return null
  }
}

// Translate a "downloading" play response into UI state and start polling.
const handleDownloadingResponse = (playResponse) => {
  status.value = 'downloading'
  if (playResponse.status === 'downloading') {
    if (playResponse.download_status === 'importing') {
      downloadProgress.value = 100
      setDownloadState({ progress: 100, status: 'importing' })
    } else {
      downloadProgress.value = playResponse.download_progress || 0
      setDownloadState({
        progress: playResponse.download_progress || 0,
        status: playResponse.download_status || 'preparing',
        phase: playResponse.download_phase,
      })
    }
  } else {
    setDownloadState({
      progress: playResponse.download_progress || 0,
      status: playResponse.download_status || playResponse.status || 'preparing',
      phase: playResponse.download_phase,
    })
  }
  loading.value = false
  startDownloadPolling()
}

// Map a startPlayback() error into status + errorMessage.
const handleStartPlaybackError = (err) => {
  if (err.response?.status === 503) {
    status.value = 'error'
    errorMessage.value = t('playPage.capacityReached')
  } else if (
    err.response?.data?.detail?.includes('No releases') ||
    err.response?.data?.detail?.includes('No file')
  ) {
    status.value = 'no-release'
  } else {
    status.value = 'error'
    errorMessage.value = err.response?.data?.detail || t('playPage.failedToStartPlayback')
  }
  loading.value = false
}

// Start playback with smart defaults (Netflix-style: just play immediately)
const startPlayback = async () => {
  if (isStartingPlayback.value) return
  isStartingPlayback.value = true

  try {
    const options = {
      video_codec: 'h264',
      audio_codec: 'aac',
      audio_bitrate: '128k',
    }
    const routeProfileId = stringRouteQuery('profile_id')
    const routeDeviceGuid = stringRouteQuery('device_guid')
    const routeMediaSourceId = stringRouteQuery('media_source_id')
    const routeStartPosition = numericRouteQuery('t')
    const routeAudioTrack = numericRouteQuery('audio_stream_index')
    const routeSubtitleStreamIndex = numericRouteQuery('subtitle_stream_index')

    if (routeProfileId) {
      options.profile_id = routeProfileId
    }
    if (routeDeviceGuid) {
      options.device_guid = routeDeviceGuid
    }
    if (routeMediaSourceId) {
      options.media_source_id = routeMediaSourceId
    }
    if (routeStartPosition !== null && routeStartPosition >= 0) {
      options.start_position = routeStartPosition
    } else if (lastPosition.value > 0) {
      options.start_position = lastPosition.value
    }
    await loadSavedTrackPreferences()
    if (routeAudioTrack !== null && routeAudioTrack >= 0) {
      options.audio_track = routeAudioTrack
      currentAudioTrackIndex.value = routeAudioTrack
    } else if (savedTrackPreferences.value?.selected_audio_track_index != null) {
      options.audio_track = savedTrackPreferences.value.selected_audio_track_index
      currentAudioTrackIndex.value = savedTrackPreferences.value.selected_audio_track_index
    }
    if (routeSubtitleStreamIndex !== null && routeSubtitleStreamIndex >= 0) {
      options.subtitle_stream_index = routeSubtitleStreamIndex
    }

    const offlineResponse = await tryOfflinePlayback()
    if (offlineResponse) {
      await setupStreamablePlayback(offlineResponse)
      return
    }

    const playResponse = await startUnifiedPlayback(uuid.value, options)

    // Book files: open in BookReader directly
    if (playResponse.book_only && playResponse.token) {
      openBookFile(playResponse)
      return
    }

    const isStreamable =
      playResponse.status === 'ready' ||
      playResponse.availability === 'streamable' ||
      playResponse.availability === 'available'

    if (isStreamable) {
      await setupStreamablePlayback(playResponse)
    } else if (
      playResponse.status === 'downloading' ||
      playResponse.availability === 'downloadable'
    ) {
      handleDownloadingResponse(playResponse)
    } else if (
      playResponse.availability === 'missing' ||
      playResponse.message?.includes('No releases')
    ) {
      status.value = 'no-release'
      loading.value = false
    } else {
      status.value = 'error'
      errorMessage.value = playResponse.message || t('playPage.failedToStartPlayback')
      loading.value = false
    }
  } catch (err) {
    handleStartPlaybackError(err)
  } finally {
    // Reset guard after a short delay to prevent rapid retries
    playbackTimers.clear(playbackGuardTimer)
    playbackGuardTimer = playbackTimers.schedule(() => {
      isStartingPlayback.value = false
    }, 1000)
  }
}

// Poll for download status (handled by useDownloadPolling composable above)

const { setupMediaSession } = useMediaSession({
  contentInfo,
  contentType,
  videoJsPlayer,
  playNextEpisode: playNextPlaybackItem,
  playPreviousEpisode: playPreviousPlaybackItem,
  getTmdbImageUrl,
})

const { subscribe: subscribeRemoteControl, unsubscribe: unsubscribeRemoteControl } =
  useRemoteControlReceiver({
    wsStore,
    videoJsPlayer,
    router,
    remoteControlStore,
    playNextEpisode: playNextPlaybackItem,
    playPreviousEpisode: playPreviousPlaybackItem,
  })

const partySync = usePartySync({
  partyStore,
  partyWs,
  videoJsPlayer,
  uuid,
  contentType,
})

// Viewing-progress (load resume, periodic updates, save on unload)
const {
  lastPosition,
  loadViewingHistory,
  updateProgress,
  reportPlaybackStarted,
  reportPlaybackStopped,
  saveProgressOnUnload,
  startProgressUpdates,
  stopProgressUpdates,
} = useViewingProgress({
  uuid,
  contentType,
  playlistId,
  playlistIndex,
  authStore,
  partySync,
  videoJsPlayer,
  contentInfo,
  videoDuration,
  duration,
  sessionId,
  playToken,
})

const { checkContent } = usePlaybackBootstrap({
  uuid,
  contentType,
  router,
  contentInfo,
  videoDuration,
  status,
  loading,
  errorMessage,
  launchGameStream,
  checkEpisodeNavigation,
  checkPlaylistNavigation,
  loadFavoriteStatus,
  loadViewingHistory,
  startPlayback,
  resetDownloadProgress,
  startDownloadPolling,
  t,
})

// Stream-source swap helpers (Tier-3 seek, audio-track switch, quality switch)
const { isPositionBuffered, setupXhrAuth, swapStreamSource } = useStreamSwap({
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
})

// Player event handlers (mounted/ready/timeupdate/ended/pause)
const { onPlayerMounted, onPlayerReady, onTimeUpdate, onVideoEnded, onVideoPause } =
  useVideoPlayerEvents({
    videoJsPlayer,
    playerState,
    videoElement,
    playToken,
    sessionId,
    streamPosition,
    transcodeStartPosition,
    bufferedAmount,
    isPlaying,
    duration,
    videoDuration,
    lastPosition,
    contentInfo,
    contentType,
    uuid,
    wsStore,
    partySync,
    setupXhrAuth,
    updateProgress,
    reportPlaybackStarted,
    reportPlaybackStopped,
    setupMediaSession,
    checkEpisodeNavigation,
    shouldAutoAdvanceOnEnded: () => contentType.value === 'episode' || !!playlistId.value,
    playNextEpisode: playNextPlaybackItem,
  })

// Fetch and navigate to the next episode
// Navigation
const goBack = () => {
  router.back()
}

const searchReleases = () => {
  if (contentType.value === 'episode') {
    router.push(`/shows/episodes/${uuid.value}/releases`)
  } else {
    router.push(`/movies/${uuid.value}/releases`)
  }
}

// Reset state for new content
const resetState = () => {
  loading.value = true
  status.value = ''
  errorMessage.value = ''
  contentInfo.value = null
  lastPosition.value = 0
  duration.value = 0
  videoDuration.value = 0
  resetDownloadProgress()
  playToken.value = ''
  sessionId.value = ''
  directStreamUrl.value = ''
  playbackTargetOptions.value = {}
  if (offlineObjectMediaGuid.value) {
    offlineStore.releaseObjectUrl(offlineObjectMediaGuid.value)
    offlineObjectMediaGuid.value = ''
  }
  currentMediaSourceId.value = null
  savedTrackPreferences.value = null
  isStartingPlayback.value = false // Reset playback guard
  resetEpisodeNavigation()
  resetPlaylistNavigation()
  isFavorited.value = false

  // Clear any existing intervals
  stopProgressUpdates()
  stopDownloadPolling()
}

// Watch for route changes (e.g., when navigating to next episode)
watch(
  () => route.params.id,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      // Stop current streaming session before loading new content
      if (sessionId.value && playToken.value) {
        stopStreaming(sessionId.value, playToken.value).catch((e) =>
          logger.debug('Failed to stop previous stream:', e.message),
        )
      }
      if (videoJsPlayer.value && duration.value > 0) {
        updateProgress(videoJsPlayer.value.currentTime(), duration.value, { eventName: 'stop' })
      }
      resetState()
      checkContent()
    }
  },
)

// Save progress and stop stream on page unload (handled by useViewingProgress composable above)

// Lifecycle
onMounted(() => {
  checkContent()

  // Initialize Watch Party (WS connection, host media patch, host sync responder)
  partySync.initialize()

  // Add beforeunload listener
  window.addEventListener('beforeunload', saveProgressOnUnload)

  // Listen for remote control commands
  subscribeRemoteControl()

  // Regular progress updates
  startProgressUpdates()
})

// === Custom Player Controls Handlers ===

// Stream-source swap helpers (isPositionBuffered, abortPendingHlsRequests,
// setupXhrAuth, swapStreamSource) come from useStreamSwap composable above.

// Handle seek request from custom controls
// 3-tier seek strategy:
//   1. Client has data buffered → instant seek (no network)
//   2. Server has transcoded segments → let Video.js fetch them
//   3. Neither → start a new transcode at the target position
const {
  handleSeek,
  handleAudioTrackChange,
  handleQualityChange,
  togglePlayPause,
  toggleMute,
  setVolume,
  toggleFullscreen,
} = usePlayerControls({
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
})

onUnmounted(() => {
  playbackTimers.clearAll()

  // Remove beforeunload listener
  window.removeEventListener('beforeunload', saveProgressOnUnload)

  // Exit fullscreen if still active
  if (document.fullscreenElement) {
    const exit = document.exitFullscreen || document.webkitExitFullscreen
    if (exit) exit.call(document)
  }

  // Remove remote control listener
  unsubscribeRemoteControl()

  if (offlineObjectMediaGuid.value) {
    offlineStore.releaseObjectUrl(offlineObjectMediaGuid.value)
    offlineObjectMediaGuid.value = ''
  }

  // Stop streaming session and cleanup resources
  if (sessionId.value && playToken.value) {
    stopStreaming(sessionId.value, playToken.value).catch((e) => {
      logger.debug('Could not stop streaming session:', e)
    })
  }

  // Final progress update - check if player and its element still exist
  // videoJsPlayer may be disposed before onUnmounted is called
  if (videoJsPlayer.value && videoJsPlayer.value.el_ && duration.value > 0) {
    try {
      updateProgress(videoJsPlayer.value.currentTime(), duration.value, { eventName: 'stop' })
    } catch (e) {
      // Player may be disposed, ignore errors
      logger.debug('Could not save final progress:', e.message)
    }
  }

  // Clear playback status when leaving the page
  wsStore.clearPlaybackStatus()
})
</script>

<style lang="scss" scoped>
.play-page {
  background: #0a0a0a;
  padding: 0;
  min-height: inherit;
}

.player-wrapper {
  position: relative;
  width: 100%;
  max-width: 100%;
  height: calc(100vh - 50px);
  overflow: hidden;
  background: #000;

  &:fullscreen,
  &:-webkit-full-screen {
    width: 100vw;
    height: 100vh;
  }
}

.video-container {
  width: 100%;
  height: 100%;

  :deep(.video-js) {
    width: 100% !important;
    height: 100% !important;
    padding-top: 0 !important;
  }

  :deep(.vjs-tech) {
    object-fit: contain;
  }
}

.custom-player-controls {
  display: none;
}
</style>
