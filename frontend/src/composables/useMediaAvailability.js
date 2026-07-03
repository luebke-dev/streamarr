import { ref } from 'vue'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'
import * as mediaService from 'src/services/mediaService'
import { logger } from 'src/utils/logger'

export function useMediaAvailability({ mediaItem, subscribe, unsubscribe, getWebSocketHandler }) {
  const availability = ref(null)
  const retryTimers = useTimeoutRegistry()

  function currentGuid() {
    return mediaItem.value?.guid ? String(mediaItem.value.guid) : null
  }

  function unsubscribeAvailabilityTarget(guid = currentGuid()) {
    const targetGuid = availability.value?.target_guid
    const handler = getWebSocketHandler?.()
    if (targetGuid && targetGuid !== String(guid) && handler) {
      unsubscribe('media_item', targetGuid, handler)
    }
  }

  async function refreshAvailability() {
    const guid = currentGuid()
    if (!guid) return

    try {
      const oldTargetGuid = availability.value?.target_guid
      const data = await mediaService.getMediaAvailability(guid)

      if (currentGuid() !== guid) return

      availability.value = data
      const handler = getWebSocketHandler?.()

      if (oldTargetGuid && oldTargetGuid !== availability.value?.target_guid && handler) {
        unsubscribe('media_item', oldTargetGuid, handler)
      }
      if (availability.value?.target_guid && availability.value.target_guid !== guid && handler) {
        subscribe('media_item', availability.value.target_guid, handler)
      }

      retryTimers.clearAll()
      if (
        availability.value?.status === 'searching' ||
        availability.value?.status === 'downloading'
      ) {
        retryTimers.schedule(refreshAvailability, 5000)
      }
    } catch (err) {
      logger.warn('Failed to refresh availability:', err)
      availability.value = null
    }
  }

  async function toggleWatch() {
    const guid = currentGuid()
    if (!guid) return

    try {
      const data = await mediaService.toggleMediaWatch(guid)
      if (availability.value) {
        availability.value.is_watched = data.is_watched
      }
    } catch (err) {
      logger.error('Error toggling watch:', err)
    }
  }

  function clearAvailabilityTimers() {
    retryTimers.clearAll()
  }

  return {
    availability,
    refreshAvailability,
    toggleWatch,
    clearAvailabilityTimers,
    unsubscribeAvailabilityTarget,
  }
}
