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
        await launchGameStream()
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
