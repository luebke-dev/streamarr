import { ref } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

export function useSongIdentification({ uuid, transcodeStartPosition, streamPosition, t }) {
  const identifyingSong = ref(false)
  const identifiedSong = ref(null)
  const showSongDialog = ref(false)
  const songError = ref(null)

  async function handleIdentifySong() {
    identifyingSong.value = true
    identifiedSong.value = null
    songError.value = null
    try {
      const currentPos = transcodeStartPosition.value + streamPosition.value
      const response = await api.post(`/api/play/${uuid.value}/identify-song`, null, {
        params: { position: currentPos },
      })
      if (response.data.status === 'identified') {
        identifiedSong.value = response.data.song
      }
      showSongDialog.value = true
    } catch (error) {
      logger.error('Failed to identify song:', error)
      const detail = error.response?.data?.detail
      songError.value = typeof detail === 'string' ? detail : t('player.identifyError')
      showSongDialog.value = true
    } finally {
      identifyingSong.value = false
    }
  }

  return {
    identifyingSong,
    identifiedSong,
    showSongDialog,
    songError,
    handleIdentifySong,
  }
}
