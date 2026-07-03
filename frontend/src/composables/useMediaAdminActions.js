import { ref } from 'vue'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'
import * as mediaService from 'src/services/mediaService'
import { logger } from 'src/utils/logger'

export function useMediaAdminActions({ mediaItem, files, releases, downloads, loadMediaItem, isSuperuser }) {
  const refreshingMetadata = ref(false)
  const searchingReleases = ref(false)
  const reprobingFiles = ref(false)
  const reprobingFileId = ref(null)
  const deletingFileId = ref(null)
  const downloadingReleaseId = ref(null)
  const timers = useTimeoutRegistry()

  function guid() {
    return mediaItem.value?.guid
  }

  function canMutateMedia() {
    return Boolean(guid() && isSuperuser.value)
  }

  async function loadReleases() {
    if (!guid()) return

    try {
      const data = await mediaService.loadMediaReleases(guid())
      releases.value = data.releases || []
    } catch (err) {
      logger.error('Error loading releases:', err)
    }
  }

  async function loadReleasesData() {
    if (!guid()) return

    try {
      const data = await mediaService.loadMediaItem(guid(), {
        load_files: false,
        load_releases: true,
        load_external_ids: false,
      })
      releases.value = data.releases || []
    } catch (err) {
      logger.error('Error reloading releases:', err)
    }
  }

  async function loadDownloadsData() {
    if (!guid() || !isSuperuser.value) return
    try {
      downloads.value = await mediaService.getMediaDownloads(guid())
    } catch (err) {
      logger.error('Error loading downloads:', err)
    }
  }

  async function handleFilesUpdated() {
    if (!guid()) return
    try {
      const data = await mediaService.loadMediaItem(guid(), {
        load_files: true,
        load_releases: false,
        load_external_ids: false,
      })
      files.value = data.files || []
    } catch (err) {
      logger.error('Failed to reload files:', err)
    }
  }

  async function searchReleases() {
    if (!canMutateMedia()) return

    searchingReleases.value = true
    try {
      await mediaService.searchMediaReleases(guid())
      timers.schedule(loadReleases, 2000)
    } catch (err) {
      logger.error('Error searching releases:', err)
    } finally {
      searchingReleases.value = false
    }
  }

  async function downloadRelease(release) {
    if (!guid() || !release?.links?.length) return

    downloadingReleaseId.value = release.guid
    try {
      await mediaService.downloadMediaRelease(guid(), release.guid)
    } catch {
      // silently ignore
    } finally {
      downloadingReleaseId.value = null
    }
  }

  async function deleteRelease(release) {
    if (!canMutateMedia() || !release) return
    try {
      await mediaService.deleteMediaRelease(guid(), release.guid)
      releases.value = releases.value.filter((item) => item.guid !== release.guid)
    } catch {
      // silently ignore
    }
  }

  async function deleteAllReleases() {
    if (!canMutateMedia()) return
    try {
      await mediaService.deleteAllMediaReleases(guid())
      releases.value = []
    } catch {
      // silently ignore
    }
  }

  async function reprobeFile(file) {
    if (!canMutateMedia() || !file) return

    reprobingFileId.value = file.guid
    try {
      await mediaService.reprobeMediaFile(guid(), file.guid)
      timers.schedule(loadMediaItem, 3000)
    } catch (err) {
      logger.error('Error reprobing file:', err)
    } finally {
      reprobingFileId.value = null
    }
  }

  async function deleteFile(file) {
    if (!canMutateMedia() || !file) return

    deletingFileId.value = file.guid
    try {
      await mediaService.deleteMediaFile(guid(), file.guid)
      files.value = files.value.filter((item) => item.guid !== file.guid)
    } catch (err) {
      logger.error('Error deleting file:', err)
    } finally {
      deletingFileId.value = null
    }
  }

  async function reprobeAllFiles() {
    if (!canMutateMedia()) return

    reprobingFiles.value = true
    try {
      await mediaService.reprobeAllMediaFiles(guid())
      timers.schedule(loadMediaItem, 5000)
    } catch (err) {
      logger.error('Error reprobing all files:', err)
    } finally {
      reprobingFiles.value = false
    }
  }

  async function refreshMetadata() {
    if (!canMutateMedia()) return

    refreshingMetadata.value = true
    try {
      await mediaService.refreshMetadata(guid())
      timers.schedule(loadMediaItem, 2000)
    } catch (err) {
      logger.error('Error refreshing metadata:', err)
    } finally {
      refreshingMetadata.value = false
    }
  }

  function clearAdminTimers() {
    timers.clearAll()
  }

  return {
    refreshingMetadata,
    searchingReleases,
    reprobingFiles,
    reprobingFileId,
    deletingFileId,
    downloadingReleaseId,
    loadReleases,
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
  }
}
