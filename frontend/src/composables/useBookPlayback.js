import { ref } from 'vue'
import { getServerUrl } from 'src/utils/authStorage'

export function useBookPlayback({ status, loading }) {
  const bookFileUrl = ref('')
  const bookFormat = ref('')
  const bookFileName = ref('')

  function openBookFile(playResponse) {
    const baseUrl = getServerUrl(window.location.origin)
    bookFileUrl.value = `${baseUrl}/api/stream/book/file?token=${playResponse.token}`
    bookFormat.value = playResponse.book_format || ''
    bookFileName.value = playResponse.file_name || ''
    status.value = 'book-reading'
    loading.value = false
  }

  return {
    bookFileUrl,
    bookFormat,
    bookFileName,
    openBookFile,
  }
}
