/**
 * Favorite-toggle composable.
 *
 * Wraps GET /api/favorites/{typePrefix}/{guid}/status and
 * POST /api/favorites/{typePrefix}/{guid} into a reactive pair.
 *
 * Usage:
 *   const target = computed(() => ({ typePrefix: 'movies', guid: item.value?.guid }))
 *   const { isFavorited, toggling, checkStatus, toggle } = useFavorite(target)
 *
 * The target may be a ref, computed, or plain object. `checkStatus` is safe
 * to call when guid is falsy (no-op). `toggle` sets `toggling` during the
 * request and syncs `isFavorited` from the server response.
 *
 * @param {import('vue').Ref<{typePrefix: string, guid: string}> | () => {typePrefix: string, guid: string}} targetSource
 * @returns {{ isFavorited: import('vue').Ref<boolean>, toggling: import('vue').Ref<boolean>, checkStatus: () => Promise<void>, toggle: () => Promise<void> }}
 */
import { ref, unref } from 'vue'
import { api } from 'boot/axios'
import { invalidateApiCache } from 'src/composables/useApiResponseCache'
import { logger } from 'src/utils/logger'

function resolveTarget(source) {
  if (typeof source === 'function') return source()
  return unref(source)
}

export function useFavorite(targetSource) {
  const isFavorited = ref(false)
  const monitored = ref(false)
  const toggling = ref(false)

  async function checkStatus() {
    const target = resolveTarget(targetSource)
    if (!target?.guid || !target?.typePrefix) return
    try {
      const response = await api.get(`/api/favorites/${target.typePrefix}/${target.guid}/status`)
      isFavorited.value = response.data.is_favorited
      monitored.value = response.data.monitored ?? false
    } catch (err) {
      logger.error('Error checking favorite status:', err)
    }
  }

  async function toggle() {
    const target = resolveTarget(targetSource)
    if (!target?.guid || !target?.typePrefix) return
    toggling.value = true
    try {
      const response = await api.post(`/api/favorites/${target.typePrefix}/${target.guid}`)
      isFavorited.value = response.data.is_favorited
      monitored.value = response.data.monitored ?? false
      invalidateApiCache('/api/favorites')
      invalidateApiCache(`/api/media/${target.guid}`)
    } catch (err) {
      logger.error('Error toggling favorite:', err)
    } finally {
      toggling.value = false
    }
  }

  return { isFavorited, monitored, toggling, checkStatus, toggle }
}
