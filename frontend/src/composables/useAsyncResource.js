/**
 * Async resource composable for fetch-once / fetch-on-param-change flows.
 *
 * Provides `data`, `loading`, `error`, and `refresh()` refs/functions with
 * built-in error handling. Call `refresh()` to (re)execute the fetcher;
 * pass `{ immediate: true }` to auto-fetch on mount, or `{ watch: sources }`
 * to auto-refresh when reactive sources change.
 *
 * @template T
 * @param {() => Promise<T>} fetcher - Async function returning the resource.
 * @param {object} [options]
 * @param {T} [options.initial=null] - Initial value for data.
 * @param {boolean} [options.immediate=false] - Auto-fetch on mount.
 * @param {import('vue').WatchSource | import('vue').WatchSource[]} [options.watch] - Sources that trigger refresh.
 * @param {(err: unknown) => void} [options.onError] - Custom error handler (logger.error is called regardless).
 * @returns {{
 *   data: import('vue').Ref<T|null>,
 *   loading: import('vue').Ref<boolean>,
 *   error: import('vue').Ref<unknown>,
 *   refresh: () => Promise<T|null>
 * }}
 */
import { ref, onMounted, watch as vueWatch } from 'vue'
import { logger } from 'src/utils/logger'

export function useAsyncResource(
  fetcher,
  { initial = null, immediate = false, watch = null, onError = null } = {},
) {
  const data = ref(initial)
  const loading = ref(false)
  const error = ref(null)
  let requestId = 0

  async function refresh() {
    const currentRequest = ++requestId
    loading.value = true
    error.value = null
    try {
      const result = await fetcher()
      if (currentRequest === requestId) {
        data.value = result
      }
      return result
    } catch (err) {
      if (currentRequest === requestId) {
        error.value = err
      }
      logger.error('useAsyncResource fetch failed:', err)
      if (onError) onError(err)
      return null
    } finally {
      if (currentRequest === requestId) {
        loading.value = false
      }
    }
  }

  if (immediate) {
    onMounted(refresh)
  }
  if (watch) {
    vueWatch(watch, () => refresh(), { deep: false })
  }

  return { data, loading, error, refresh }
}
