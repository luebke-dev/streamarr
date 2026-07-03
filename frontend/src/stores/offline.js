import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from 'src/boot/axios'
import { useAuthStore } from './auth'
import { logger } from 'src/utils/logger'

export const useOfflineStore = defineStore('offline', () => {
  const currentDevice = ref(null)
  const manifest = ref(null)
  const deviceOfflineItems = ref({})
  const deviceManifests = ref({})
  const loading = ref(false)
  const error = ref(null)
  const requestErrorMessage = ref('')
  const objectUrls = ref({})

  const manifestItems = computed(() => manifest.value?.items || [])
  const statusOrder = ['queued', 'downloading', 'ready', 'failed', 'removed']

  function errorDetail(err) {
    const detail = err?.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((item) => item.msg || item.message).join(', ')
    return err?.message || 'Offline sync request failed'
  }

  function isExpired(item) {
    return item?.expires_at ? new Date(item.expires_at).getTime() <= Date.now() : false
  }

  function offlineStatusCounts(items = []) {
    const counts = Object.fromEntries(statusOrder.map((status) => [status, 0]))
    for (const item of items) {
      if (counts[item.status] == null) counts[item.status] = 0
      counts[item.status] += 1
    }
    return counts
  }

  async function loadCurrentDevice({ force = false } = {}) {
    if (currentDevice.value && !force) return currentDevice.value

    const authStore = useAuthStore()
    const response = await api.get('/api/devices/me', {
      params: { page_size: 100 },
    })
    const devices = response.data?.items || []
    currentDevice.value =
      devices.find((device) => device.device_id === authStore.deviceId) || devices[0] || null
    return currentDevice.value
  }

  async function fetchDeviceOfflineItems(deviceGuid, { force = false } = {}) {
    if (!deviceGuid) return { items: [], total: 0 }
    if (deviceOfflineItems.value[deviceGuid] && !force) {
      return deviceOfflineItems.value[deviceGuid]
    }

    const response = await api.get(`/api/devices/${deviceGuid}/offline-items`)
    const payload = response.data || { items: [], total: 0 }
    deviceOfflineItems.value = {
      ...deviceOfflineItems.value,
      [deviceGuid]: payload,
    }
    return payload
  }

  async function fetchManifest({ force = false, deviceGuid = null } = {}) {
    const device = deviceGuid ? null : await loadCurrentDevice({ force })
    const targetDeviceGuid = deviceGuid || device?.guid
    if (!targetDeviceGuid) {
      manifest.value = { items: [], total: 0 }
      return manifest.value
    }
    if (deviceGuid && deviceManifests.value[deviceGuid] && !force) {
      return deviceManifests.value[deviceGuid]
    }
    if (!deviceGuid && manifest.value && !force) return manifest.value

    loading.value = true
    error.value = null
    try {
      const response = await api.get(`/api/devices/${targetDeviceGuid}/offline-items/manifest`)
      const payload = response.data || { items: [], total: 0 }
      deviceManifests.value = {
        ...deviceManifests.value,
        [targetDeviceGuid]: payload,
      }
      if (!deviceGuid || currentDevice.value?.guid === targetDeviceGuid) {
        manifest.value = payload
      }
      return payload
    } catch (err) {
      error.value = err
      logger.warn('[Offline] Failed to load offline manifest:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  function findManifestItem(mediaGuid) {
    return manifestItems.value.find(
      (item) =>
        item.media_guid === mediaGuid &&
        item.status === 'ready' &&
        item.download_url &&
        !isExpired(item),
    )
  }

  async function createObjectUrlForMedia(mediaGuid, { force = false } = {}) {
    if (!mediaGuid) return null
    if (objectUrls.value[mediaGuid] && !force) return objectUrls.value[mediaGuid]
    if (objectUrls.value[mediaGuid] && force) releaseObjectUrl(mediaGuid)

    await fetchManifest({ force })
    const item = findManifestItem(mediaGuid)
    if (!item) return null

    const response = await api.get(item.download_url, { responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    objectUrls.value = {
      ...objectUrls.value,
      [mediaGuid]: { url, item },
    }
    return objectUrls.value[mediaGuid]
  }

  function releaseObjectUrl(mediaGuid) {
    const entry = objectUrls.value[mediaGuid]
    if (entry?.url) URL.revokeObjectURL(entry.url)
    const next = { ...objectUrls.value }
    delete next[mediaGuid]
    objectUrls.value = next
  }

  async function requestOfflineSync(mediaGuids, { deviceGuid = null, expiresAt = null } = {}) {
    requestErrorMessage.value = ''
    try {
      const device = deviceGuid ? null : await loadCurrentDevice()
      const targetDeviceGuid = deviceGuid || device?.guid
      if (!targetDeviceGuid) throw new Error('No device is available for offline sync')
      const response = await api.post(
        `/api/devices/${targetDeviceGuid}/offline-items/sync-request`,
        {
          media_guids: Array.isArray(mediaGuids) ? mediaGuids : [mediaGuids],
          ...(expiresAt ? { expires_at: expiresAt } : {}),
        },
      )
      const payload = response.data || { items: [], total: 0 }
      deviceOfflineItems.value = {
        ...deviceOfflineItems.value,
        [targetDeviceGuid]: payload,
      }
      manifest.value = null
      const nextManifests = { ...deviceManifests.value }
      delete nextManifests[targetDeviceGuid]
      deviceManifests.value = nextManifests
      return payload
    } catch (err) {
      requestErrorMessage.value = errorDetail(err)
      logger.warn('[Offline] Offline sync request failed:', err)
      throw err
    }
  }

  function clearObjectUrls() {
    for (const entry of Object.values(objectUrls.value)) {
      if (entry?.url) URL.revokeObjectURL(entry.url)
    }
    objectUrls.value = {}
  }

  function resetManifest() {
    manifest.value = null
    error.value = null
  }

  return {
    currentDevice,
    manifest,
    manifestItems,
    deviceOfflineItems,
    deviceManifests,
    objectUrls,
    loading,
    error,
    requestErrorMessage,
    statusOrder,
    offlineStatusCounts,
    loadCurrentDevice,
    fetchDeviceOfflineItems,
    fetchManifest,
    findManifestItem,
    createObjectUrlForMedia,
    requestOfflineSync,
    releaseObjectUrl,
    clearObjectUrls,
    resetManifest,
  }
})
