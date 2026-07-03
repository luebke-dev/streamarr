import { ref } from 'vue'
import { api } from 'boot/axios'
import { useInterval } from 'src/composables/useInterval'
import { useWebSocket } from 'src/composables/useWebSocket'
import { getMediaItem } from 'src/composables/useUnifiedMedia'
import { logger } from 'src/utils/logger'

/**
 * Polls the backend for download progress while a media item is still being
 * downloaded, and (preferred) listens for the WebSocket `media_available` event
 * to resume playback as soon as the file is on disk.
 *
 * The composable owns the polling lifecycle (interval + ws subscription) and
 * exposes:
 *   - downloadProgress (ref<number>) – 0..100
 *   - downloadStatus (ref<string>) – backend status, normalized for display
 *   - downloadPhase (ref<string>) – UI phase derived from status/progress
 *   - setDownloadState() – seed the state from an initial play response
 *   - start()  – begin polling and ws-subscribe (call after a download starts)
 *   - stop()   – cancel polling and unsubscribe
 *   - reset()  – clear progress/status state
 *
 * Args:
 *   - uuid (Ref<string>)            – the current media item id
 *   - status (Ref<string>)          – playback status string ('' to clear)
 *   - loading (Ref<boolean>)        – global loading flag
 *   - videoDuration (Ref<number>)   – set on first availability
 *   - onAvailable (() => Promise)   – called when the file becomes available
 *                                     (typically: startPlayback)
 */
export function useDownloadPolling({ uuid, status, loading, videoDuration, onAvailable }) {
  const wsStore = useWebSocket()
  const downloadProgress = ref(0)
  const downloadStatus = ref('')
  const downloadPhase = ref('')

  let downloadUnsubscribe = null
  let pollerTick = null
  let lastNonZeroProgress = 0
  const poller = useInterval(() => pollerTick?.(), 5000)

  function normalizeDownloadStatus(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_')
  }

  function normalizeProgress(value) {
    if (value == null) return null
    const progress = Number(value)
    if (!Number.isFinite(progress)) return null
    return Math.min(100, Math.max(0, progress))
  }

  function deriveDownloadPhase(nextStatus, nextProgress) {
    const activeStatuses = new Set(['pending', 'queued', 'preparing', 'downloading'])
    const retryStatuses = new Set(['failed', 'retrying', 'retrying_release'])

    if (retryStatuses.has(nextStatus)) {
      return 'retrying_release'
    }

    if (
      lastNonZeroProgress >= 5 &&
      nextProgress != null &&
      nextProgress <= 1 &&
      activeStatuses.has(nextStatus)
    ) {
      return 'retrying_release'
    }

    if (downloadPhase.value === 'retrying_release' && activeStatuses.has(nextStatus)) {
      return 'retrying_release'
    }

    if (nextStatus === 'completed' || nextStatus === 'importing') {
      return 'importing'
    }

    return nextStatus
  }

  function setDownloadState({ progress, status: nextStatus, availabilityStatus, phase } = {}) {
    const normalizedStatus = normalizeDownloadStatus(nextStatus || availabilityStatus)
    const normalizedProgress = normalizeProgress(progress)
    const normalizedPhase = normalizeDownloadStatus(phase)

    if (normalizedStatus) {
      downloadStatus.value = normalizedStatus
    }

    const derivedPhase = normalizedPhase || deriveDownloadPhase(normalizedStatus, normalizedProgress)
    if (derivedPhase) {
      downloadPhase.value = derivedPhase
    }

    if (normalizedProgress != null) {
      downloadProgress.value = normalizedProgress
      if (normalizedProgress > 1) {
        lastNonZeroProgress = normalizedProgress
      }
    }
  }

  function reset() {
    downloadProgress.value = 0
    downloadStatus.value = ''
    downloadPhase.value = ''
    lastNonZeroProgress = 0
  }

  async function resumePlayback() {
    stop()
    status.value = ''
    loading.value = true
    await onAvailable()
  }

  function start() {
    poller.stop()

    if (wsStore.isConnected.value) {
      wsStore.send({
        action: 'subscribe',
        resource_type: 'media_item',
        resource_id: String(uuid.value),
      })
      downloadUnsubscribe = wsStore.on('media_available', resumePlayback)
    }

    pollerTick = async () => {
      try {
        // Poll a read-only endpoint for live download progress. The play
        // endpoint has side effects (download/transcode starts, rate limits)
        // and must not be used as a progress probe.
        try {
          const availabilityResp = await api.get(`/api/media/${uuid.value}/availability`)
          const availability = availabilityResp.data || {}
          const currentDownloadStatus = String(availability.download_status || '').toLowerCase()

          setDownloadState({
            progress: availability.download_progress,
            status: availability.download_status,
            phase: availability.download_phase,
            availabilityStatus: availability.status,
          })

          if (currentDownloadStatus === 'completed' || currentDownloadStatus === 'importing') {
            downloadProgress.value = 100
            setDownloadState({ progress: 100, status: 'importing' })
          }

          if (availability.status === 'available') {
            await resumePlayback()
            return
          }
        } catch (e) {
          // Progress polling: tolerate transient errors, just log for diagnostics
          logger.debug('Progress fetch failed', e)
        }

        const mediaData = await getMediaItem(uuid.value, {
          load_files: true,
          load_releases: false,
          load_external_ids: false,
        })

        if (mediaData.files && mediaData.files.length > 0) {
          stop()
          if (wsStore.isConnected.value) {
            wsStore.send({
              action: 'unsubscribe',
              resource_type: 'media_item',
              resource_id: String(uuid.value),
            })
          }
          videoDuration.value = mediaData.duration || 0
          status.value = ''
          loading.value = true
          await onAvailable()
        }
      } catch (error) {
        if (error.response?.status === 401) {
          await resumePlayback()
        } else {
          // Don't spam on every poll tick, but do log so failures are diagnosable
          logger.debug('Download poll error', error)
        }
      }
    }
    poller.start()
  }

  function stop() {
    poller.stop()
    downloadUnsubscribe?.()
    downloadUnsubscribe = null
  }

  return {
    downloadProgress,
    downloadStatus,
    downloadPhase,
    setDownloadState,
    start,
    stop,
    reset,
  }
}
