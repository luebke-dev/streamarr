// usePictureInPicture — encapsulates Picture-in-Picture state and toggle
// for an HTMLVideoElement (passed as a reactive ref/computed).
// Tracks browser-driven PiP exit via leavepictureinpicture listener and
// cleanly removes it on element change / unmount.
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { logger } from 'src/utils/logger'

export function usePictureInPicture(videoElementRef) {
  const isPip = ref(false)
  const pipSupported = computed(() => !!document.pictureInPictureEnabled)

  const onLeavePip = () => {
    isPip.value = false
  }

  const togglePip = async () => {
    const el = videoElementRef.value
    if (!el) return
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture()
        isPip.value = false
      } else {
        await el.requestPictureInPicture()
        isPip.value = true
      }
    } catch (e) {
      logger.warn('PiP not available:', e)
    }
  }

  let currentEl = null
  const stopWatch = watch(
    () => videoElementRef.value,
    (el) => {
      if (currentEl) {
        currentEl.removeEventListener('leavepictureinpicture', onLeavePip)
      }
      currentEl = el
      if (el) {
        el.addEventListener('leavepictureinpicture', onLeavePip)
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    if (currentEl) {
      currentEl.removeEventListener('leavepictureinpicture', onLeavePip)
      currentEl = null
    }
    stopWatch()
  })

  return { isPip, pipSupported, togglePip }
}
