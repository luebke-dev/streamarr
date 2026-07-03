import { computed, ref } from 'vue'
import * as mediaService from 'src/services/mediaService'
import { logger } from 'src/utils/logger'

export function useMediaProviderRepair({ mediaItem, t, onMediaUpdated }) {
  const providerRepairTab = ref('subtitles')
  const subtitleSearch = ref({ language: 'en', provider: '', query: '' })
  const subtitleResults = ref([])
  const subtitleLoading = ref(false)
  const subtitleDownloading = ref(null)
  const lyricsSearch = ref({ provider: '', query: '' })
  const lyricsResults = ref([])
  const lyricsLoading = ref(false)
  const lyricsDownloading = ref(null)
  const artworkSearch = ref({ imageType: 'poster', language: '', provider: '' })
  const artworkResults = ref([])
  const artworkLoading = ref(false)
  const artworkSelecting = ref(null)
  const artworkUploadFile = ref(null)
  const artworkUploading = ref(false)
  const artworkTypeOptions = computed(() => [
    { label: t('mediaDetail.poster'), value: 'poster' },
    { label: t('mediaDetail.backdrop'), value: 'backdrop' },
  ])

  function guid() {
    return mediaItem.value?.guid
  }

  async function notifyMediaUpdated() {
    await onMediaUpdated?.()
  }

  async function searchSubtitles() {
    if (!guid()) return
    subtitleLoading.value = true
    try {
      const data = await mediaService.searchSubtitles(guid(), {
        language: subtitleSearch.value.language || undefined,
        provider: subtitleSearch.value.provider || undefined,
        query: subtitleSearch.value.query || undefined,
      })
      subtitleResults.value = data.items || []
    } catch (err) {
      logger.error('Error searching subtitles:', err)
    } finally {
      subtitleLoading.value = false
    }
  }

  async function downloadSubtitle(item) {
    if (!guid() || !item) return
    subtitleDownloading.value = item.provider_id
    try {
      await mediaService.downloadSubtitle(guid(), {
        provider: item.provider,
        provider_id: item.provider_id,
        title: item.title || item.file_name,
        make_default: false,
      })
      await notifyMediaUpdated()
    } catch (err) {
      logger.error('Error downloading subtitle:', err)
    } finally {
      subtitleDownloading.value = null
    }
  }

  async function searchLyrics() {
    if (!guid()) return
    lyricsLoading.value = true
    try {
      const data = await mediaService.searchLyrics(guid(), {
        provider: lyricsSearch.value.provider || undefined,
        query: lyricsSearch.value.query || undefined,
      })
      lyricsResults.value = data.items || []
    } catch (err) {
      logger.error('Error searching lyrics:', err)
    } finally {
      lyricsLoading.value = false
    }
  }

  async function downloadLyrics(item) {
    if (!guid() || !item) return
    lyricsDownloading.value = item.provider_id
    try {
      await mediaService.downloadLyrics(guid(), {
        provider: item.provider,
        provider_id: item.provider_id,
      })
      await notifyMediaUpdated()
    } catch (err) {
      logger.error('Error downloading lyrics:', err)
    } finally {
      lyricsDownloading.value = null
    }
  }

  async function searchArtwork() {
    if (!guid()) return
    artworkLoading.value = true
    try {
      const data = await mediaService.searchArtwork(guid(), {
        image_type: artworkSearch.value.imageType,
        language: artworkSearch.value.language || undefined,
        provider: artworkSearch.value.provider || undefined,
        include_language_neutral: true,
      })
      artworkResults.value = data.items || []
    } catch (err) {
      logger.error('Error searching artwork:', err)
    } finally {
      artworkLoading.value = false
    }
  }

  async function selectArtwork(item) {
    if (!guid() || !item) return
    artworkSelecting.value = item.provider_id
    try {
      await mediaService.selectRemoteArtwork(guid(), item.image_type, {
        provider: item.provider,
        provider_id: item.provider_id,
      })
      await notifyMediaUpdated()
    } catch (err) {
      logger.error('Error selecting artwork:', err)
    } finally {
      artworkSelecting.value = null
    }
  }

  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        const result = String(reader.result || '')
        resolve(result.includes(',') ? result.split(',').pop() : result)
      }
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })
  }

  async function uploadArtwork() {
    if (!guid() || !artworkUploadFile.value) return
    artworkUploading.value = true
    try {
      const file = artworkUploadFile.value
      const contentBase64 = await readFileAsBase64(file)
      await mediaService.uploadArtwork(guid(), artworkSearch.value.imageType, {
        content_base64: contentBase64,
        content_type: file.type,
        file_name: file.name,
      })
      artworkUploadFile.value = null
      await notifyMediaUpdated()
    } catch (err) {
      logger.error('Error uploading artwork:', err)
    } finally {
      artworkUploading.value = false
    }
  }

  return {
    providerRepairTab,
    subtitleSearch,
    subtitleResults,
    subtitleLoading,
    subtitleDownloading,
    lyricsSearch,
    lyricsResults,
    lyricsLoading,
    lyricsDownloading,
    artworkSearch,
    artworkResults,
    artworkLoading,
    artworkSelecting,
    artworkUploadFile,
    artworkUploading,
    artworkTypeOptions,
    searchSubtitles,
    downloadSubtitle,
    searchLyrics,
    downloadLyrics,
    searchArtwork,
    selectArtwork,
    uploadArtwork,
  }
}
