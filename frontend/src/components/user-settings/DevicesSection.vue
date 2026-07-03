<template>
  <div class="q-mb-lg">
    <q-card flat bordered>
      <q-card-section>
        <div class="text-h6 q-mb-sm">
          <q-icon name="mdi-devices" class="q-mr-sm" />
          {{ $t('settings.devices') }}
        </div>
        <div class="text-body2 text-grey-6 q-mb-lg">
          {{ $t('settings.devicesDescription') }}
        </div>

        <q-linear-progress v-if="loading" indeterminate color="primary" class="q-mb-md" />

        <div v-if="!loading && devices.length === 0" class="text-center text-grey-6 q-py-xl">
          <q-icon name="mdi-devices-off" size="64px" class="q-mb-md" />
          <div class="text-h6">{{ $t('settings.noDevices') }}</div>
        </div>

        <div v-else class="row q-col-gutter-md">
          <div v-for="device in devices" :key="device.guid" class="col-12 col-sm-6 col-md-4">
            <q-card flat bordered class="device-card">
              <q-card-section class="text-center">
                <q-avatar size="64px" color="primary" text-color="white" class="q-mb-md">
                  <q-icon :name="getDeviceIcon(device)" size="32px" />
                </q-avatar>

                <div class="text-h6 q-mb-xs">
                  {{ device.name || device.browser || $t('settings.unknown') }}
                </div>

                <div class="q-mb-sm">
                  <q-badge
                    v-if="isCurrentDevice(device)"
                    color="green"
                    :label="$t('settings.currentDevice')"
                    class="q-mr-xs"
                  />
                </div>

                <q-separator class="q-my-sm" />

                <div class="text-caption text-grey-7 text-left">
                  <div class="q-mb-xs">
                    <q-icon name="mdi-laptop" size="xs" class="q-mr-xs" />
                    {{ device.platform || device.browser || $t('settings.unknown') }}
                  </div>
                  <div class="q-mb-xs">
                    <q-icon name="mdi-clock-outline" size="xs" class="q-mr-xs" />
                    {{ formatDeviceDate(device.last_activity) }}
                  </div>
                  <div v-if="device.last_ip_address">
                    <q-icon name="mdi-ip-network" size="xs" class="q-mr-xs" />
                    {{ device.last_ip_address }}
                  </div>
                </div>
              </q-card-section>

              <q-separator />

              <q-card-section class="q-pt-sm">
                <div class="row items-center justify-between q-mb-xs">
                  <div class="text-subtitle2">{{ $t('settings.offlineManifest') }}</div>
                  <q-btn
                    flat
                    round
                    dense
                    icon="mdi-refresh"
                    :loading="offlineLoading[device.guid]"
                    @click="loadOfflineState(device)"
                  />
                </div>
                <q-banner
                  v-if="offlineErrors[device.guid]"
                  dense
                  rounded
                  class="bg-negative text-white q-mb-sm"
                >
                  {{ offlineErrors[device.guid] }}
                </q-banner>
                <div class="row q-gutter-xs q-mb-sm">
                  <q-chip
                    v-for="status in offlineStatuses"
                    :key="status"
                    dense
                    size="sm"
                    :color="offlineStatusColor(status)"
                    text-color="white"
                    :label="`${offlineStatusLabel(status)} ${offlineCounts(device)[status] || 0}`"
                  />
                </div>
                <div v-if="offlineItems(device).length === 0" class="text-caption text-grey-6">
                  {{ $t('settings.noOfflineItems') }}
                </div>
                <q-list v-else dense separator>
                  <q-item v-for="item in offlineItems(device)" :key="item.media_guid">
                    <q-item-section>
                      <q-item-label lines="1">
                        {{ item.media_title || item.media_guid }}
                      </q-item-label>
                      <q-item-label caption>
                        {{ offlineItemSummary(device, item) }}
                      </q-item-label>
                      <q-linear-progress
                        v-if="item.status === 'downloading'"
                        :value="offlineProgress(item)"
                        color="primary"
                        class="q-mt-xs"
                      />
                    </q-item-section>
                    <q-item-section side>
                      <q-chip
                        dense
                        size="sm"
                        :color="offlineStatusColor(item.status)"
                        text-color="white"
                        :label="offlineStatusLabel(item.status)"
                      />
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-card-section>

              <q-separator />

              <q-card-actions align="center">
                <q-btn
                  flat
                  dense
                  color="primary"
                  icon="mdi-pencil"
                  :label="$t('common.edit')"
                  size="sm"
                  @click="editDevice(device)"
                />
                <q-btn
                  flat
                  dense
                  color="negative"
                  icon="mdi-delete"
                  :label="$t('common.delete')"
                  size="sm"
                  @click="confirmRemoveDevice(device)"
                />
              </q-card-actions>
            </q-card>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <!-- Edit Device Dialog -->
    <q-dialog v-model="showEditDeviceDialog">
      <q-card dark style="width: 400px; max-width: 95vw">
        <q-card-section>
          <div class="text-h6">{{ $t('settings.editDeviceTitle') }}</div>
        </q-card-section>

        <q-card-section>
          <q-input
            v-model="editDeviceForm.name"
            :label="$t('settings.customDeviceName')"
            :hint="$t('settings.customDeviceNameHint')"
            outlined
            autofocus
          />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="$t('common.cancel')" color="grey-7" />
          <q-btn
            flat
            :label="$t('common.save')"
            color="primary"
            :loading="savingDevice"
            @click="saveDeviceEdit"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import * as deviceService from 'src/services/deviceService'
import { logger } from 'src/utils/logger'
import { getStoredDeviceId } from 'src/utils/deviceIdentity'
import { useOfflineStore } from 'src/stores/offline'

const emit = defineEmits(['current-device-removed'])

const $q = useQuasar()
const { t, locale } = useI18n({ useScope: 'global' })
const offlineStore = useOfflineStore()

const devices = ref([])
const loading = ref(false)
const currentDeviceId = ref(null)
const showEditDeviceDialog = ref(false)
const editDeviceForm = ref({ guid: null, name: '' })
const savingDevice = ref(false)
const offlineStates = ref({})
const offlineLoading = ref({})
const offlineErrors = ref({})
const offlineStatuses = offlineStore.statusOrder

async function loadDevices() {
  loading.value = true
  try {
    devices.value = await deviceService.getMyDevices()

    const storedDeviceId = getStoredDeviceId()
    if (storedDeviceId) {
      currentDeviceId.value = storedDeviceId
    }

    await Promise.all(devices.value.map((device) => loadOfflineState(device)))
  } catch (error) {
    logger.error('Failed to load devices:', error)
  } finally {
    loading.value = false
  }
}

function getDeviceIcon(device) {
  const platform = (device?.platform || '').toLowerCase()
  const browser = (device?.browser || '').toLowerCase()
  const userAgent = (device?.user_agent || '').toLowerCase()

  if (platform.includes('android') || userAgent.includes('android')) {
    return 'mdi-cellphone-android'
  }
  if (platform.includes('ios') || platform.includes('iphone') || userAgent.includes('iphone')) {
    return 'mdi-cellphone-iphone'
  }
  if (platform.includes('mobile') || userAgent.includes('mobile')) {
    return 'mdi-cellphone'
  }
  if (platform.includes('ipad') || userAgent.includes('ipad')) {
    return 'mdi-tablet-ipad'
  }
  if (platform.includes('tablet')) {
    return 'mdi-tablet'
  }
  if (platform.includes('tv') || userAgent.includes('tv')) {
    return 'mdi-television'
  }
  if (platform.includes('mac') || platform.includes('darwin')) {
    return 'mdi-apple'
  }
  if (platform.includes('windows') || platform.includes('win')) {
    return 'mdi-microsoft-windows'
  }
  if (platform.includes('linux')) {
    return 'mdi-linux'
  }
  if (browser.includes('chrome')) return 'mdi-google-chrome'
  if (browser.includes('firefox')) return 'mdi-firefox'
  if (browser.includes('safari')) return 'mdi-apple-safari'
  if (browser.includes('edge')) return 'mdi-microsoft-edge'

  return 'mdi-devices'
}

function isCurrentDevice(device) {
  return device.guid === currentDeviceId.value || device.device_id === currentDeviceId.value
}

function formatDeviceDate(dateString) {
  if (!dateString) return t('settings.never')
  const date = new Date(dateString)
  return date.toLocaleString(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function offlineItems(device) {
  return offlineStates.value[device.guid]?.items || []
}

function offlineManifestItems(device) {
  return offlineStates.value[device.guid]?.manifestItems || []
}

function offlineCounts(device) {
  return offlineStore.offlineStatusCounts(offlineItems(device))
}

function offlineStatusColor(status) {
  const colors = {
    queued: 'grey-7',
    downloading: 'info',
    ready: 'positive',
    failed: 'negative',
    removed: 'warning',
  }
  return colors[status] || 'grey'
}

function offlineStatusLabel(status) {
  const labels = {
    queued: t('settings.offlineQueued'),
    downloading: t('settings.offlineDownloading'),
    ready: t('settings.offlineReady'),
    failed: t('settings.offlineFailed'),
    removed: t('settings.offlineRemoved'),
  }
  return labels[status] || status
}

function offlineProgress(item) {
  return Math.max(0, Math.min(100, Number(item.progress) || 0)) / 100
}

function manifestEntry(device, item) {
  return offlineManifestItems(device).find(
    (manifestItem) => manifestItem.media_guid === item.media_guid,
  )
}

function offlineItemSummary(device, item) {
  if (item.error_message) return item.error_message
  const parts = []
  if (item.progress != null && item.status === 'downloading') {
    parts.push(t('settings.offlineProgress', { progress: Math.round(item.progress) }))
  }
  if (item.expires_at) {
    parts.push(t('settings.offlineExpires', { date: formatDeviceDate(item.expires_at) }))
  }
  const manifestItem = manifestEntry(device, item)
  if (manifestItem?.subtitles?.length) {
    parts.push(t('settings.offlineSubtitles', { count: manifestItem.subtitles.length }))
  }
  return parts.join(' · ') || item.media_type || t('settings.unknown')
}

function offlineErrorMessage(error) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error.message || t('settings.offlineLoadError')
}

async function loadOfflineState(device) {
  if (!device?.guid) return
  offlineLoading.value = { ...offlineLoading.value, [device.guid]: true }
  offlineErrors.value = { ...offlineErrors.value, [device.guid]: '' }
  try {
    const [itemsResponse, manifestResponse] = await Promise.all([
      offlineStore.fetchDeviceOfflineItems(device.guid, { force: true }),
      offlineStore.fetchManifest({ deviceGuid: device.guid, force: true }),
    ])
    offlineStates.value = {
      ...offlineStates.value,
      [device.guid]: {
        items: itemsResponse.items || [],
        manifestItems: manifestResponse.items || [],
      },
    }
  } catch (error) {
    logger.error('Failed to load offline state:', error)
    offlineErrors.value = { ...offlineErrors.value, [device.guid]: offlineErrorMessage(error) }
  } finally {
    offlineLoading.value = { ...offlineLoading.value, [device.guid]: false }
  }
}

function editDevice(device) {
  editDeviceForm.value = {
    guid: device.guid,
    name: device.name || device.device_name || '',
  }
  showEditDeviceDialog.value = true
}

async function saveDeviceEdit() {
  savingDevice.value = true
  try {
    await deviceService.updateMyDevice(editDeviceForm.value.guid, {
      name: editDeviceForm.value.name,
    })
    showEditDeviceDialog.value = false
    await loadDevices()
  } catch (error) {
    logger.error('Failed to update device:', error)
  } finally {
    savingDevice.value = false
  }
}

function confirmRemoveDevice(device) {
  $q.dialog({
    title: t('settings.removeDeviceTitle'),
    message: t('settings.removeDeviceMessage'),
    cancel: { flat: true, label: t('common.cancel') },
    ok: { flat: true, label: t('settings.removeDevice'), color: 'negative' },
    persistent: true,
  }).onOk(async () => {
    await removeDevice(device)
  })
}

async function removeDevice(device) {
  try {
    await deviceService.removeMyDevice(device.guid)
    await loadDevices()

    if (isCurrentDevice(device)) {
      emit('current-device-removed')
    }
  } catch (error) {
    logger.error('Failed to remove device:', error)
  }
}

onMounted(() => {
  loadDevices()
})
</script>
