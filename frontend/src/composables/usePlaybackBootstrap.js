import { getMediaItem } from 'src/composables/useUnifiedMedia'
import { logger } from 'src/utils/logger'

export function usePlaybackBootstrap({
  uuid,
  contentType,
  router,
  contentInfo,
  videoDuration,
  status,
  loading,
  errorMessage,
  launchGameStream,
  fetchGamePlatforms,
  checkEpisodeNavigation,
  checkPlaylistNavigation,
  loadFavoriteStatus,
  loadViewingHistory,
  startPlayback,
  resetDownloadProgress,
  startDownloadPolling,
  t,
}) {
  let checkContentInFlight = false

  async function checkContent() {
    if (checkContentInFlight) return
    checkContentInFlight = true

    loading.value = true
    errorMessage.value = ''

    try {
      if (contentType.value === 'music') {
        const { useAudioPlayerStore } = await import('stores/audioPlayer')
        const audioPlayer = useAudioPlayerStore()
        const mediaData = await getMediaItem(uuid.value, {
          load_files: true,
          load_releases: false,
          load_external_ids: false,
        })
        audioPlayer.play({ guid: uuid.value, title: mediaData.title, ...mediaData })
        router.back()
        return
      }

      if (contentType.value === 'game') {
        // Load the game's metadata so the shared download-waiting screen can
        // show its poster/title (same PlayStatusScreen movies/episodes use).
        try {
          contentInfo.value = await getMediaItem(uuid.value, {
            load_files: false,
            load_releases: false,
            load_external_ids: false,
          })
        } catch (e) {
          logger.debug('Failed to load game metadata for play screen', e)
        }

        // Let the player pick a platform/version when the game offers more than
        // one (e.g. N64 ROM vs PC port); otherwise launch straight away.
        const platforms = fetchGamePlatforms ? await fetchGamePlatforms() : []
        if (Array.isArray(platforms) && platforms.length > 1) {
          status.value = 'game-platform-select'
          loading.value = false
          return
        }
        await launchGameStream(platforms?.[0]?.platform ?? null)
        // No ROM yet → launchGameStream set status='downloading' and the backend
        // kicked off acquisition. Start the SAME polling as movies; it relaunches
        // the game (onAvailable) once the ROM lands.
        if (status.value === 'downloading' && startDownloadPolling) {
          startDownloadPolling()
        }
        return
      }

      const mediaData = await getMediaItem(uuid.value, {
        load_files: true,
        load_releases: false,
        load_external_ids: false,
      })
      contentInfo.value = mediaData
      checkEpisodeNavigation()
      checkPlaylistNavigation()
      await Promise.all([loadFavoriteStatus(), loadViewingHistory()])

      const hasFiles = mediaData.files && mediaData.files.length > 0

      if (hasFiles) {
        videoDuration.value = mediaData.duration || 0
        await startPlayback()
      } else if (mediaData.availability === 'downloadable') {
        status.value = 'downloading'
        resetDownloadProgress()
        loading.value = false
        startDownloadPolling()
      } else {
        await startPlayback()
      }
    } catch (error) {
      logger.error('Failed to initialize playback', error)
      status.value = 'error'
      errorMessage.value = error.response?.data?.detail || t('playPage.failedToLoadContent')
      loading.value = false
    } finally {
      checkContentInFlight = false
    }
  }

  return {
    checkContent,
  }
}
