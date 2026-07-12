<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminDevices.title') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md items-center">
          <div class="col-12 col-md-6">
            <q-input
              v-model="filter"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
              debounce="300"
            >
              <template v-slot:prepend><q-icon name="mdi-magnify" /></template>
            </q-input>
          </div>
          <div class="col-12 col-md-6 row justify-end items-center">
            <q-toggle v-model="showInactive" :label="$t('adminDevices.showInactive')" />
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          ref="tableRef"
          :rows="rows"
          :columns="columns"
          row-key="guid"
          v-model:pagination="pagination"
          :loading="loading"
          :filter="filter"
          binary-state-sort
          @request="onRequest"
        >
          <template v-slot:body-cell-device_info="props">
            <q-td :props="props">
              <div class="row items-center">
                <q-icon :name="getBrowserIcon(props.row.browser)" size="sm" class="q-mr-sm" />
                <div>
                  <div>{{ props.row.browser || $t('common.unknown') }}</div>
                  <div class="text-caption text-grey">
                    {{ props.row.platform || $t('common.unknown') }}
                  </div>
                </div>
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-user="props">
            <q-td :props="props">
              <div>{{ props.row.user_name || $t('common.unknown') }}</div>
              <div class="text-caption text-grey">{{ props.row.user_email }}</div>
            </q-td>
          </template>

          <template v-slot:body-cell-playback_status="props">
            <q-td :props="props">
              <div v-if="props.row.is_playing" class="playback-status playing">
                <q-icon name="mdi-play-circle" color="positive" size="sm" class="q-mr-xs" />
                <div class="playback-info">
                  <div class="playback-title">
                    {{ props.row.current_media_title || $t('common.unknown') }}
                  </div>
                  <div class="text-caption text-grey">
                    {{ formatMediaType(props.row.current_media_type) }} ·
                    {{ formatPlaybackTime(props.row.current_playback_position) }} /
                    {{ formatPlaybackTime(props.row.current_playback_duration) }}
                  </div>
                  <q-linear-progress
                    :value="getPlaybackProgress(props.row)"
                    color="primary"
                    size="4px"
                    class="q-mt-xs"
                  />
                </div>
                <q-tooltip>
                  {{
                    $t('adminDevices.lastUpdatedAt', {
                      time: formatRelativeTime(props.row.playback_updated_at),
                    })
                  }}
                </q-tooltip>
              </div>
              <div v-else class="text-grey">
                <q-icon name="mdi-pause-circle" size="sm" class="q-mr-xs" />
                {{ $t('adminDevices.idle') }}
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-is_active="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-check-circle' : 'mdi-cancel'"
                :color="props.value ? 'positive' : 'negative'"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-is_ws_connected="props">
            <q-td :props="props" class="text-center">
              <q-icon
                :name="props.value ? 'mdi-circle' : 'mdi-circle-outline'"
                :color="props.value ? 'positive' : 'grey-5'"
                size="sm"
              >
                <q-tooltip>{{
                  props.value ? $t('adminDevices.online') : $t('adminDevices.offline')
                }}</q-tooltip>
              </q-icon>
            </q-td>
          </template>

          <template v-slot:body-cell-last_activity="props">
            <q-td :props="props">
              <q-tooltip>{{ formatDate(props.value) }}</q-tooltip>
              {{ formatRelativeTime(props.value) }}
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                size="sm"
                color="secondary"
                round
                dense
                icon="mdi-card-account-details-outline"
                @click="viewDeviceSession(props.row)"
                class="q-mr-xs"
              >
                <q-tooltip>{{ $t('adminDevices.viewSession') }}</q-tooltip>
              </q-btn>
              <q-btn
                size="sm"
                color="primary"
                round
                dense
                icon="mdi-pencil"
                @click="editDevice(props.row)"
                class="q-mr-xs"
              />
              <q-btn
                size="sm"
                color="negative"
                round
                dense
                icon="mdi-delete"
                @click="confirmDelete(props.row)"
              />
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Device Edit Dialog -->
    <q-dialog v-model="showEditDialog" persistent>
      <q-card dark style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminDevices.editTitle') }}</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="saveDevice" class="q-gutter-md">
            <q-input
              outlined
              dark
              dense
              v-model="deviceForm.name"
              :label="$t('adminDevices.deviceName')"
              :hint="$t('adminDevices.deviceNameHint')"
            />

            <div class="text-caption q-mt-md">
              <div>
                <strong>{{ $t('adminDevices.fieldDeviceId') }}:</strong> {{ deviceForm.device_id }}
              </div>
              <div>
                <strong>{{ $t('adminDevices.fieldBrowser') }}:</strong>
                {{ deviceForm.browser || $t('common.unknown') }}
              </div>
              <div>
                <strong>{{ $t('adminDevices.fieldPlatform') }}:</strong>
                {{ deviceForm.platform || $t('common.unknown') }}
              </div>
              <div>
                <strong>{{ $t('adminDevices.fieldLastIp') }}:</strong>
                {{ deviceForm.last_ip_address || $t('common.unknown') }}
              </div>
              <div>
                <strong>{{ $t('adminDevices.fieldLastActivity') }}:</strong>
                {{ formatDate(deviceForm.last_activity) }}
              </div>
            </div>
          </q-form>
        </q-card-section>

        <q-card-actions align="right" class="text-primary">
          <q-btn flat :label="$t('common.cancel')" @click="cancelEdit" />
          <q-btn flat :label="$t('common.save')" @click="saveDevice" :loading="saving" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Native Session Details Dialog -->
    <q-dialog v-model="showSessionDialog">
      <q-card dark style="min-width: 520px; max-width: 760px">
        <q-card-section class="row items-center q-gutter-sm">
          <q-icon name="mdi-card-account-details-outline" color="secondary" size="sm" />
          <div class="text-h6">{{ $t('adminDevices.sessionTitle') }}</div>
          <q-space />
          <q-btn
            flat
            round
            dense
            icon="mdi-refresh"
            :loading="sessionLoading"
            @click="loadDeviceSession()"
          />
        </q-card-section>

        <q-separator />

        <q-card-section v-if="sessionLoading" class="text-center q-pa-lg">
          <q-spinner color="primary" size="32px" />
        </q-card-section>

        <q-card-section v-else-if="!selectedSession" class="text-grey">
          {{ $t('adminDevices.sessionUnavailable') }}
        </q-card-section>

        <q-card-section v-else class="q-gutter-md">
          <q-list dense bordered separator>
            <q-item>
              <q-item-section>
                <q-item-label caption>{{ $t('adminDevices.fieldDeviceId') }}</q-item-label>
                <q-item-label class="text-mono">{{ sessionDevice.device_id }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge
                  :color="sessionDevice.is_ws_connected ? 'positive' : 'grey'"
                  :label="
                    sessionDevice.is_ws_connected
                      ? $t('adminDevices.onlineShort')
                      : $t('adminDevices.offlineShort')
                  "
                />
              </q-item-section>
            </q-item>

            <q-item>
              <q-item-section>
                <q-item-label caption>{{ $t('adminDevices.sessionConnection') }}</q-item-label>
                <q-item-label>{{ sessionConnectionSummary }}</q-item-label>
              </q-item-section>
            </q-item>

            <q-item v-if="sessionNowPlaying">
              <q-item-section>
                <q-item-label caption>{{ $t('adminDevices.nowPlaying') }}</q-item-label>
                <q-item-label>{{
                  sessionNowPlaying.media_title || $t('common.unknown')
                }}</q-item-label>
                <q-item-label caption>
                  {{ formatMediaType(sessionNowPlaying.media_type) }} ·
                  {{ formatPlaybackTime(sessionNowPlaying.position_seconds) }} /
                  {{ formatPlaybackTime(sessionNowPlaying.duration_seconds) }}
                </q-item-label>
                <q-linear-progress
                  :value="(sessionNowPlaying.progress_percentage || 0) / 100"
                  color="primary"
                  size="5px"
                  class="q-mt-xs"
                />
              </q-item-section>
              <q-item-section side>
                <q-badge
                  :color="sessionNowPlaying.is_playing ? 'positive' : 'warning'"
                  :label="
                    sessionNowPlaying.is_playing
                      ? $t('adminDevices.playing')
                      : $t('adminDevices.paused')
                  "
                />
              </q-item-section>
            </q-item>

            <q-item>
              <q-item-section>
                <q-item-label caption>{{ $t('adminDevices.capabilities') }}</q-item-label>
                <q-item-label>{{ sessionCapabilitySummary }}</q-item-label>
                <div class="q-mt-xs q-gutter-xs">
                  <q-chip
                    v-for="command in visibleSessionCommands"
                    :key="command"
                    dense
                    square
                    color="grey-8"
                    text-color="white"
                  >
                    {{ command }}
                  </q-chip>
                </div>
              </q-item-section>
            </q-item>

            <q-item>
              <q-item-section>
                <q-item-label caption>{{ $t('adminDevices.queueState') }}</q-item-label>
                <q-item-label>{{ sessionQueueSummary }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>

          <div v-if="sessionRecentCommands.length > 0">
            <div class="text-subtitle2 q-mb-sm">{{ $t('adminDevices.recentCommands') }}</div>
            <q-list dense bordered separator>
              <q-item v-for="command in sessionRecentCommands" :key="command.guid">
                <q-item-section>
                  <q-item-label>{{ command.message }}</q-item-label>
                  <q-item-label caption>{{ formatDate(command.created_at) }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.close')" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminDevices.deleteConfirm')"
      :loading="deleting"
      @confirm="deleteDevice"
    >
      <q-card-section>
        <q-toggle v-model="permanentDelete" :label="$t('adminDevices.permanentDelete')" />
      </q-card-section>
    </ConfirmDeleteDialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  listDevices,
  deleteDevice as deleteDeviceRequest,
  updateDevice,
  getDeviceSession,
} from 'src/services/deviceService'
import { useAdminCrudList } from 'src/composables/useAdminCrudList'
import { logger } from 'src/utils/logger'
import { formatTime } from 'src/composables/useMediaFormatters'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()
const saving = ref(false)
const showInactive = ref(false)
const showEditDialog = ref(false)
const showSessionDialog = ref(false)
const sessionLoading = ref(false)
const selectedSessionDevice = ref(null)
const selectedSession = ref(null)
const permanentDelete = ref(false)

const {
  tableRef,
  rows,
  filter,
  loading,
  pagination,
  onRequest,
  refresh,
  showDeleteDialog,
  deleting,
  confirmDelete,
  performDelete: deleteDevice,
} = useAdminCrudList({
  fetchPage: async ({ page, rowsPerPage, filter }) => {
    const params = {
      page,
      page_size: rowsPerPage,
      include_inactive: showInactive.value,
    }
    if (filter) params.search = filter
    const data = await listDevices(params)
    return { items: data.items, total: data.total }
  },
  deleteItem: (device) => deleteDeviceRequest(device.guid, permanentDelete.value),
  initialPagination: { sortBy: 'last_activity', rowsPerPage: 20 },
  errorContext: 'devices',
})

const deviceForm = ref({
  guid: null,
  device_id: '',
  name: '',
  browser: '',
  platform: '',
  last_ip_address: '',
  last_activity: '',
})

const sessionDevice = computed(
  () => selectedSession.value?.device || selectedSessionDevice.value || {},
)
const sessionNowPlaying = computed(() => selectedSession.value?.now_playing || null)
const sessionCapabilities = computed(() => selectedSession.value?.capabilities || {})
const sessionQueueState = computed(() => selectedSession.value?.queue_state || {})
const sessionRecentCommands = computed(() => selectedSession.value?.recent_commands || [])
const visibleSessionCommands = computed(() =>
  (sessionCapabilities.value.supported_commands || []).slice(0, 8),
)
const sessionConnectionSummary = computed(() => {
  const active = selectedSession.value?.active_session
  if (!active) return t('adminDevices.noActiveSession')
  return t('adminDevices.activeSessionSummary', {
    connections: active.connection_count,
    subscriptions: active.subscription_count,
    lastSeen: formatRelativeTime(active.last_seen_at),
  })
})
const sessionCapabilitySummary = computed(() => {
  const profile = sessionCapabilities.value.profile_id || t('common.unknown')
  const codecs = [
    ...(sessionCapabilities.value.supported_video_codecs || []),
    ...(sessionCapabilities.value.supported_audio_codecs || []),
  ].slice(0, 5)
  return codecs.length
    ? `${profile} · ${codecs.join(', ')}`
    : t('adminDevices.profileOnly', { profile })
})
const sessionQueueSummary = computed(() => {
  const items = sessionQueueState.value.items || []
  if (!items.length) return t('adminDevices.queueEmpty')
  const current =
    items[sessionQueueState.value.current_index ?? sessionQueueState.value.start_index ?? 0]
  return t('adminDevices.queueSummary', {
    count: items.length,
    current: current?.media_title || current?.title || t('common.unknown'),
  })
})

const columns = computed(() => [
  {
    name: 'device_info',
    required: true,
    label: t('adminDevices.colDevice'),
    align: 'left',
    field: 'browser',
    sortable: true,
  },
  {
    name: 'user',
    align: 'left',
    label: t('adminDevices.colUser'),
    field: 'user_email',
    sortable: true,
  },
  {
    name: 'name',
    align: 'left',
    label: t('adminDevices.colName'),
    field: 'name',
    sortable: true,
  },
  {
    name: 'playback_status',
    align: 'left',
    label: t('adminDevices.colPlaybackStatus'),
    field: 'is_playing',
    sortable: true,
    style: 'min-width: 220px',
  },
  {
    name: 'last_activity',
    align: 'left',
    label: t('adminDevices.colLastActivity'),
    field: 'last_activity',
    sortable: true,
  },
  {
    name: 'last_ip_address',
    align: 'left',
    label: t('adminDevices.colIpAddress'),
    field: 'last_ip_address',
    sortable: false,
  },
  {
    name: 'is_active',
    align: 'center',
    label: t('adminDevices.colActive'),
    field: 'is_active',
    sortable: true,
  },
  {
    name: 'is_ws_connected',
    align: 'center',
    label: t('adminDevices.colOnline'),
    field: 'is_ws_connected',
    sortable: false,
  },
  {
    name: 'created_at',
    align: 'left',
    label: t('adminDevices.colFirstSeen'),
    field: 'created_at',
    format: (val) => (val ? parseUtcDate(val).toLocaleDateString() : '-'),
    sortable: true,
  },
  {
    name: 'actions',
    align: 'center',
    label: t('common.actions'),
    field: 'actions',
  },
])

function editDevice(device) {
  deviceForm.value = {
    guid: device.guid,
    device_id: device.device_id,
    name: device.name || '',
    browser: device.browser,
    platform: device.platform,
    last_ip_address: device.last_ip_address,
    last_activity: device.last_activity,
  }
  showEditDialog.value = true
}

function cancelEdit() {
  showEditDialog.value = false
  deviceForm.value = {
    guid: null,
    device_id: '',
    name: '',
    browser: '',
    platform: '',
    last_ip_address: '',
    last_activity: '',
  }
}

async function saveDevice() {
  saving.value = true
  try {
    await updateDevice(deviceForm.value.guid, {
      name: deviceForm.value.name || null,
    })

    refresh()
    cancelEdit()
  } catch (error) {
    logger.error('Error updating device:', error)
  } finally {
    saving.value = false
  }
}

function viewDeviceSession(device) {
  selectedSessionDevice.value = device
  selectedSession.value = null
  showSessionDialog.value = true
  loadDeviceSession(device)
}

async function loadDeviceSession(device = selectedSessionDevice.value) {
  if (!device?.guid) return
  sessionLoading.value = true
  try {
    selectedSession.value = await getDeviceSession(device.guid)
  } catch (error) {
    selectedSession.value = null
    logger.error('Error loading device session:', error)
  } finally {
    sessionLoading.value = false
  }
}

function getBrowserIcon(browser) {
  const browserLower = (browser || '').toLowerCase()
  if (browserLower.includes('chrome')) return 'mdi-google-chrome'
  if (browserLower.includes('firefox')) return 'mdi-firefox'
  if (browserLower.includes('safari')) return 'mdi-apple-safari'
  if (browserLower.includes('edge')) return 'mdi-microsoft-edge'
  return 'mdi-web'
}

function parseUtcDate(dateString) {
  if (!dateString) return null
  // Backend returns naive UTC timestamps without 'Z' — force UTC parsing
  const s = dateString.endsWith('Z') || dateString.includes('+') ? dateString : dateString + 'Z'
  return new Date(s)
}

function formatDate(dateString) {
  if (!dateString) return t('adminDevices.never')
  return parseUtcDate(dateString).toLocaleString()
}

function formatRelativeTime(dateString) {
  if (!dateString) return t('adminDevices.never')
  const date = parseUtcDate(dateString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return t('adminDevices.justNow')
  if (diffMins < 60) return t('adminDevices.minutesAgo', { count: diffMins })
  if (diffHours < 24) return t('adminDevices.hoursAgo', { count: diffHours })
  if (diffDays < 7) return t('adminDevices.daysAgo', { count: diffDays })
  return date.toLocaleDateString()
}

function formatPlaybackTime(seconds) {
  // Guard non-positive values to '0:00' (matches prior behavior), then delegate
  // the h:mm:ss / m:ss breakdown to the canonical formatter. For seconds > 0 the
  // shared formatTime is byte-identical to the previous local implementation.
  if (!seconds || seconds <= 0) return '0:00'
  return formatTime(seconds)
}

function formatMediaType(mediaType) {
  if (!mediaType) return t('common.unknown')
  const types = {
    movie: t('movie.label'),
    episode: t('show.episode'),
    music: t('music'),
  }
  return types[mediaType] || mediaType
}

function getPlaybackProgress(device) {
  if (!device.current_playback_duration || device.current_playback_duration <= 0) return 0
  return device.current_playback_position / device.current_playback_duration
}

watch(showInactive, () => {
  refresh()
})

// Reset permanentDelete each time the dialog opens (mirrors original behavior)
watch(showDeleteDialog, (open) => {
  if (open) permanentDelete.value = false
})

onMounted(() => {
  refresh()
})
</script>

<style lang="scss" scoped>
.playback-status {
  display: flex;
  align-items: flex-start;
  gap: 4px;

  &.playing {
    .playback-info {
      flex: 1;
      min-width: 0;
    }

    .playback-title {
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 180px;
    }
  }
}

.text-mono {
  font-family: 'Courier New', monospace;
  font-size: 0.9em;
}
</style>
