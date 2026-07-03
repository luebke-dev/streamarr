/**
 * Lifecycle-safe setInterval composable.
 *
 * Returns `start` / `stop` / `isActive` and automatically clears the timer
 * on component unmount. If `immediate` is true, the timer starts on mount.
 *
 * @param {() => void | Promise<void>} callback - Function invoked on each tick.
 * @param {number} intervalMs - Interval in milliseconds.
 * @param {object} [options]
 * @param {boolean} [options.immediate=false] - Start on mount.
 * @param {boolean} [options.runImmediately=false] - Invoke callback once right after start.
 * @returns {{ start: () => void, stop: () => void, isActive: import('vue').Ref<boolean> }}
 */
import { ref, onBeforeUnmount, onMounted } from 'vue'

export function useInterval(
  callback,
  intervalMs,
  { immediate = false, runImmediately = false } = {},
) {
  const isActive = ref(false)
  let timer = null

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    isActive.value = false
  }

  function start() {
    if (timer) return
    if (runImmediately) {
      try {
        callback()
      } catch {
        // swallow — consumer handles its own errors
      }
    }
    timer = setInterval(callback, intervalMs)
    isActive.value = true
  }

  if (immediate) {
    onMounted(start)
  }
  onBeforeUnmount(stop)

  return { start, stop, isActive }
}
