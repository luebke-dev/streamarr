import { ref, onMounted, onUnmounted } from 'vue'
import { logger } from 'src/utils/logger'

/**
 * Progress bar interaction logic for the custom player controls.
 *
 * Encapsulates click/tap-to-seek, drag-to-seek (mouse + touch), and
 * rAF-throttled hover preview. Emits a single `seek(positionInSeconds)`
 * event via the supplied callback whenever the user commits a position.
 *
 * @param {Object} options
 * @param {Ref<HTMLElement|null>} options.progressBar - Template ref to the
 *   progress container element used for geometry queries and hover events.
 * @param {Ref<boolean>} options.isDragging - Shared flag, set true while a
 *   drag is in progress so e.g. auto-hide can keep the controls visible.
 * @param {() => number} options.getTotalDuration - Returns total playable
 *   duration in seconds. Called per interaction so the latest value is used.
 * @param {(seconds: number) => void} options.onSeek - Called when the user
 *   commits a new playback position.
 * @returns {Object} Reactive state + handlers to bind in the template.
 */
export function useProgressBar({ progressBar, isDragging, getTotalDuration, onSeek }) {
  const hoverTime = ref(null)
  const hoverPercent = ref(0)

  // Cache the progress bar's rect for the lifetime of a drag so we don't
  // trigger a layout read on every pixel of movement.
  let progressBarRect = null
  let hoverRafHandle = null
  let pendingHoverX = null

  const getClientX = (e) => {
    if (e.touches && e.touches.length > 0) return e.touches[0].clientX
    if (e.changedTouches && e.changedTouches.length > 0) return e.changedTouches[0].clientX
    return e.clientX
  }

  const handleProgressClick = (e) => {
    if (!progressBar.value) return

    const rect = progressBar.value.getBoundingClientRect()
    const percent = Math.max(0, Math.min(1, (getClientX(e) - rect.left) / rect.width))
    const totalDuration = getTotalDuration()
    const seekPosition = percent * totalDuration

    logger.debug('[useProgressBar] Progress click:', {
      percent,
      totalDuration,
      seekPosition,
    })

    if (totalDuration > 0) {
      onSeek(seekPosition)
    } else {
      logger.warn('[useProgressBar] Cannot seek: totalDuration is 0')
    }
  }

  const startDragging = () => {
    isDragging.value = true
    progressBarRect = progressBar.value?.getBoundingClientRect() || null
    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragEnd)
    document.addEventListener('touchmove', onDragMove, { passive: false })
    document.addEventListener('touchend', onDragEnd)
    document.addEventListener('touchcancel', onDragEnd)
  }

  const onDragMove = (e) => {
    if (!isDragging.value || !progressBarRect) return
    if (e.cancelable) e.preventDefault()

    const percent = Math.max(
      0,
      Math.min(1, (getClientX(e) - progressBarRect.left) / progressBarRect.width),
    )
    hoverTime.value = percent * getTotalDuration()
    hoverPercent.value = percent * 100
  }

  const onDragEnd = (e) => {
    const rect = progressBarRect || progressBar.value?.getBoundingClientRect()
    progressBarRect = null
    if (!rect) return

    const percent = Math.max(0, Math.min(1, (getClientX(e) - rect.left) / rect.width))
    const seekPosition = percent * getTotalDuration()

    isDragging.value = false
    hoverTime.value = null
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
    document.removeEventListener('touchmove', onDragMove)
    document.removeEventListener('touchend', onDragEnd)
    document.removeEventListener('touchcancel', onDragEnd)

    onSeek(seekPosition)
  }

  // Touch tap on progress bar (tap-to-seek)
  const handleProgressTouch = (e) => {
    if (!progressBar.value) return
    startDragging()
    onDragMove(e)
  }

  // Progress bar hover for preview — rAF-throttled so a fast cursor doesn't
  // trigger a rect read + reactive write per mouse pixel.
  const handleProgressHover = (e) => {
    if (!progressBar.value || isDragging.value) return
    pendingHoverX = e.clientX
    if (hoverRafHandle != null) return
    hoverRafHandle = requestAnimationFrame(() => {
      hoverRafHandle = null
      if (pendingHoverX == null || !progressBar.value || isDragging.value) return
      const rect = progressBar.value.getBoundingClientRect()
      const percent = Math.max(0, Math.min(1, (pendingHoverX - rect.left) / rect.width))
      hoverTime.value = percent * getTotalDuration()
      hoverPercent.value = percent * 100
      pendingHoverX = null
    })
  }

  const handleProgressLeave = () => {
    if (!isDragging.value) {
      hoverTime.value = null
    }
  }

  onMounted(() => {
    if (progressBar.value) {
      progressBar.value.addEventListener('mousemove', handleProgressHover)
      progressBar.value.addEventListener('mouseleave', handleProgressLeave)
    }
  })

  onUnmounted(() => {
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
    document.removeEventListener('touchmove', onDragMove)
    document.removeEventListener('touchend', onDragEnd)
    document.removeEventListener('touchcancel', onDragEnd)

    if (progressBar.value) {
      progressBar.value.removeEventListener('mousemove', handleProgressHover)
      progressBar.value.removeEventListener('mouseleave', handleProgressLeave)
    }

    if (hoverRafHandle != null) {
      cancelAnimationFrame(hoverRafHandle)
      hoverRafHandle = null
    }
  })

  return {
    hoverTime,
    hoverPercent,
    handleProgressClick,
    handleProgressTouch,
    startDragging,
  }
}
