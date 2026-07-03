import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from 'src/boot/axios'

/**
 * Fetches a background image from /api/auth/background and rotates it
 * every `intervalMs` milliseconds (default: 10 seconds).
 * Also exposes the media title the background image belongs to.
 */
export function useBackgroundRotation(intervalMs = 10000) {
  const backgroundUrl = ref(null)
  const backgroundTitle = ref(null)

  const backgroundStyle = computed(() => {
    if (!backgroundUrl.value) return {}
    return {
      backgroundImage: `linear-gradient(rgba(0,0,0,0.65), rgba(0,0,0,0.65)), url(${backgroundUrl.value})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
    }
  })

  let timer = null

  const fetchBackground = async () => {
    try {
      const res = await api.get('/api/auth/background')
      backgroundUrl.value = res.data.url
      if (res.data.title) {
        backgroundTitle.value = res.data.year
          ? `${res.data.title} (${res.data.year})`
          : res.data.title
      } else {
        backgroundTitle.value = null
      }
    } catch {
      // background is optional, ignore errors
    }
  }

  onMounted(async () => {
    await fetchBackground()
    timer = setInterval(fetchBackground, intervalMs)
  })

  onUnmounted(() => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })

  return { backgroundUrl, backgroundTitle, backgroundStyle }
}
