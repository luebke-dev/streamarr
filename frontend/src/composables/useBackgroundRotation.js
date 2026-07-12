import { ref, computed } from 'vue'
import { api } from 'src/boot/axios'
import { useInterval } from './useInterval'

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

  // useInterval registers its onBeforeUnmount cleanup synchronously at setup
  // time and starts the timer on mount, so an in-flight fetch can never install
  // an orphaned interval after the component has already unmounted.
  useInterval(fetchBackground, intervalMs, { immediate: true, runImmediately: true })

  return { backgroundUrl, backgroundTitle, backgroundStyle }
}
