// useControlsAutoHide — manages controls visibility for a video player overlay.
// Controls are shown on user interaction (mousemove/touch) and hidden after
// `delayMs` of inactivity, but only while the player is actively playing
// and the user is not dragging the progress bar.
import { ref, onBeforeUnmount } from 'vue'

export function useControlsAutoHide({ delayMs = 3000, isPlayingRef, isDraggingRef } = {}) {
  const controlsVisible = ref(true)
  let hideTimeout = null

  const clearHideTimeout = () => {
    if (hideTimeout) {
      clearTimeout(hideTimeout)
      hideTimeout = null
    }
  }

  const scheduleHideControls = () => {
    clearHideTimeout()
    hideTimeout = setTimeout(() => {
      const playing = isPlayingRef ? isPlayingRef.value : true
      const dragging = isDraggingRef ? isDraggingRef.value : false
      if (playing && !dragging) {
        controlsVisible.value = false
      }
    }, delayMs)
  }

  const showControls = () => {
    controlsVisible.value = true
    scheduleHideControls()
  }

  onBeforeUnmount(() => {
    clearHideTimeout()
  })

  return { controlsVisible, showControls, scheduleHideControls }
}
