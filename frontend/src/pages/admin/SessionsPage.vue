<template>
  <q-page class="q-pa-md">
    <div class="row items-center justify-between q-mb-md">
      <div class="text-h4">{{ $t('sessionsPage.title') }}</div>
      <div class="row q-gutter-sm">
        <q-btn
          color="warning"
          icon="mdi-broom"
          :label="$t('sessionsPage.cleanup')"
          @click="runCleanup"
          :loading="cleanupLoading"
          no-caps
        >
          <q-tooltip>{{ $t('sessionsPage.cleanupTooltip') }}</q-tooltip>
        </q-btn>
        <q-btn
          color="negative"
          icon="mdi-stop"
          :label="$t('sessionsPage.terminateAll')"
          @click="confirmTerminateAll"
          :disable="sessions.length === 0"
          no-caps
        />
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-sm-4">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <div class="text-h3 text-primary">{{ stats.total }}</div>
            <div class="text-caption text-grey">{{ $t('sessionsPage.totalSessions') }}</div>
          </q-card-section>
        </q-card>
      </div>
      <div class="col-12 col-sm-4">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <div class="text-h3 text-positive">{{ stats.active }}</div>
            <div class="text-caption text-grey">{{ $t('sessionsPage.active') }}</div>
          </q-card-section>
        </q-card>
      </div>
      <div class="col-12 col-sm-4">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <div class="text-h3 text-info">{{ uniqueUsers }}</div>
            <div class="text-caption text-grey">{{ $t('sessionsPage.uniqueUsers') }}</div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Sessions Table -->
    <q-card flat bordered>
      <q-table
        :rows="sessions"
        :columns="columns"
        row-key="session_id"
        :loading="loading"
        flat
        bordered
        dark
        :rows-per-page-options="[10, 20, 50]"
        :pagination="{ rowsPerPage: 20 }"
      >
        <!-- User Column -->
        <template v-slot:body-cell-user="props">
          <q-td :props="props">
            <div class="row items-center no-wrap">
              <q-avatar size="32px" color="primary" text-color="white" class="q-mr-sm">
                {{ getUserInitials(props.row) }}
              </q-avatar>
              <div>
                <div class="text-weight-medium">
                  {{ props.row.user_name || $t('sessionsPage.anonymous') }}
                </div>
                <div class="text-caption text-grey">{{ props.row.user_guid || '-' }}</div>
              </div>
            </div>
          </q-td>
        </template>

        <!-- Content Column -->
        <template v-slot:body-cell-content="props">
          <q-td :props="props">
            <div>
              <div class="text-weight-medium">
                {{ props.row.content_title || $t('sessionsPage.unknown') }}
              </div>
              <div class="text-caption text-grey">
                <q-chip
                  :icon="getContentIcon(props.row.content_type)"
                  :label="props.row.content_type"
                  size="sm"
                  color="grey-8"
                />
              </div>
            </div>
          </q-td>
        </template>

        <!-- Codecs Column -->
        <template v-slot:body-cell-codecs="props">
          <q-td :props="props">
            <div class="row q-gutter-xs">
              <q-chip size="sm" color="blue-grey-8" text-color="white">
                {{ props.row.video_codec }}
              </q-chip>
              <q-chip size="sm" color="blue-grey-8" text-color="white">
                {{ props.row.audio_codec }}
              </q-chip>
            </div>
            <div class="text-caption text-grey q-mt-xs">
              {{ props.row.resolution || $t('sessionsPage.original') }}
              <span v-if="props.row.video_bitrate"> · {{ props.row.video_bitrate }}</span>
            </div>
          </q-td>
        </template>

        <!-- Duration Column -->
        <template v-slot:body-cell-duration="props">
          <q-td :props="props">
            <div class="text-weight-medium">
              {{ formatLongDuration(props.row.duration_seconds) }}
            </div>
            <div class="text-caption text-grey">
              {{ $t('sessionsPage.started') }}:
              {{ props.row.started_at ? new Date(props.row.started_at).toLocaleTimeString() : '-' }}
            </div>
          </q-td>
        </template>

        <!-- Progress Column -->
        <template v-slot:body-cell-progress="props">
          <q-td :props="props">
            <div v-if="props.row.transcode_progress != null" class="q-gutter-xs">
              <q-linear-progress
                :value="props.row.transcode_progress"
                color="primary"
                track-color="grey-8"
                rounded
                style="height: 6px"
              />
              <div class="text-caption text-grey">
                {{ Math.round(props.row.transcode_progress * 100) }}%
                <span v-if="props.row.transcoded_segments">
                  ({{ props.row.transcoded_segments
                  }}<span v-if="props.row.total_segments">/{{ props.row.total_segments }}</span>
                  segments)
                </span>
              </div>
            </div>
            <div v-else class="text-caption text-grey">-</div>
          </q-td>
        </template>

        <!-- Status Column -->
        <template v-slot:body-cell-status="props">
          <q-td :props="props">
            <q-chip v-bind="statusChipProps(props.row)" text-color="white" size="sm" />
          </q-td>
        </template>

        <!-- Actions Column -->
        <template v-slot:body-cell-actions="props">
          <q-td :props="props">
            <q-btn
              color="negative"
              icon="mdi-stop"
              flat
              round
              size="sm"
              @click="confirmTerminateSession(props.row)"
            >
              <q-tooltip>{{ $t('sessionsPage.terminateSession') }}</q-tooltip>
            </q-btn>
            <q-btn
              color="info"
              icon="mdi-information"
              flat
              round
              size="sm"
              @click="showSessionDetails(props.row)"
            >
              <q-tooltip>{{ $t('sessionsPage.viewDetails') }}</q-tooltip>
            </q-btn>
          </q-td>
        </template>

        <!-- No Data -->
        <template v-slot:no-data>
          <div class="full-width q-pa-xl text-center">
            <q-icon name="mdi-monitor-off" size="4em" color="grey-5" class="q-mb-md" />
            <div class="text-h6 text-grey-5">{{ $t('sessionsPage.noActiveSessions') }}</div>
            <div class="text-caption text-grey">
              {{ $t('sessionsPage.noActiveSessionsHint') }}
            </div>
          </div>
        </template>
      </q-table>
    </q-card>

    <q-card flat bordered class="q-mt-md">
      <q-card-section class="row items-center justify-between">
        <div class="text-h6">{{ $t('sessionsPage.deviceSessions') }}</div>
        <q-btn
          flat
          round
          dense
          icon="mdi-refresh"
          :aria-label="$t('common.refresh')"
          @click="loadSessions"
        />
      </q-card-section>
      <q-table
        :rows="deviceSessions"
        :columns="deviceSessionColumns"
        row-key="device_id"
        :loading="loading"
        flat
        bordered
        dark
        :rows-per-page-options="[10, 20, 50]"
        :pagination="{ rowsPerPage: 10 }"
      >
        <template v-slot:body-cell-device="props">
          <q-td :props="props">
            <div class="text-weight-medium">
              {{ props.row.device_name || props.row.browser || props.row.device_id }}
            </div>
            <div class="text-caption text-grey">
              {{ props.row.platform || '-' }} · {{ props.row.connection_count }}
              {{ $t('sessionsPage.connections') }}
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-nowPlaying="props">
          <q-td :props="props">
            <div class="text-weight-medium">
              {{ props.row.current_media_title || $t('sessionsPage.nothingPlaying') }}
            </div>
            <div class="text-caption text-grey">
              <span v-if="props.row.current_media_type">{{ props.row.current_media_type }} · </span>
              {{ formatTime(props.row.current_playback_position || 0) }}
              <span v-if="props.row.current_playback_duration">
                / {{ formatTime(props.row.current_playback_duration) }}
              </span>
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-state="props">
          <q-td :props="props">
            <q-chip
              :color="props.row.is_playing ? 'positive' : 'grey'"
              :icon="props.row.is_playing ? 'mdi-play-circle' : 'mdi-pause-circle'"
              :label="props.row.playback_state"
              text-color="white"
              size="sm"
            />
          </q-td>
        </template>

        <template v-slot:body-cell-actions="props">
          <q-td :props="props">
            <q-btn
              color="info"
              icon="mdi-information"
              flat
              round
              size="sm"
              :disable="!props.row.device_guid"
              @click="showDeviceSessionDetails(props.row)"
            >
              <q-tooltip>{{ $t('sessionsPage.viewDetails') }}</q-tooltip>
            </q-btn>
          </q-td>
        </template>

        <template v-slot:no-data>
          <div class="full-width q-pa-xl text-center">
            <q-icon name="mdi-devices" size="4em" color="grey-5" class="q-mb-md" />
            <div class="text-h6 text-grey-5">{{ $t('sessionsPage.noDeviceSessions') }}</div>
          </div>
        </template>
      </q-table>
    </q-card>

    <!-- Session Details Dialog -->
    <q-dialog v-model="showDetailsDialog">
      <q-card dark style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ $t('sessionsPage.sessionDetails') }}</div>
        </q-card-section>

        <q-card-section v-if="selectedSession" class="q-pt-none">
          <q-list dense>
            <q-item v-for="field in detailFields" :key="field.key">
              <q-item-section>
                <q-item-label caption>{{ $t(`sessionsPage.${field.key}`) }}</q-item-label>
                <q-item-label>
                  <code v-if="field.code">{{ field.value }}</code>
                  <template v-else>{{ field.value }}</template>
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>

          <template v-if="sessionContractLoading || sessionContract">
            <q-separator class="q-my-md" />
            <div class="text-subtitle2 q-mb-sm">{{ $t('sessionsPage.deviceContract') }}</div>
            <div v-if="sessionContractLoading" class="row items-center q-gutter-sm">
              <q-spinner color="primary" size="sm" />
              <span class="text-caption">{{ $t('sessionsPage.loadingDeviceContract') }}</span>
            </div>
            <q-list v-else dense bordered class="rounded-borders">
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('sessionsPage.nowPlaying') }}</q-item-label>
                  <q-item-label>{{ nowPlayingSummary }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('sessionsPage.queue') }}</q-item-label>
                  <q-item-label>{{ queueSummary }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('sessionsPage.capabilities') }}</q-item-label>
                  <div class="row q-gutter-xs q-mt-xs">
                    <q-chip
                      v-for="command in capabilityCommands"
                      :key="command"
                      size="sm"
                      color="blue-grey-8"
                      text-color="white"
                    >
                      {{ command }}
                    </q-chip>
                    <q-chip
                      v-if="sessionContract?.capabilities?.supports_play_queue"
                      size="sm"
                      color="positive"
                      text-color="white"
                    >
                      {{ $t('sessionsPage.queueSupported') }}
                    </q-chip>
                    <q-chip
                      v-if="sessionContract?.capabilities?.supports_volume_control"
                      size="sm"
                      color="positive"
                      text-color="white"
                    >
                      {{ $t('sessionsPage.volumeSupported') }}
                    </q-chip>
                  </div>
                </q-item-section>
              </q-item>
              <q-item v-if="recentCommands.length">
                <q-item-section>
                  <q-item-label caption>{{ $t('sessionsPage.recentCommands') }}</q-item-label>
                  <q-item-label v-for="command in recentCommands" :key="command.guid" caption>
                    {{ command.message || command.event_type }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('sessionsPage.close')" color="primary" v-close-popup />
          <q-btn
            flat
            :label="$t('sessionsPage.terminate')"
            color="negative"
            @click="confirmTerminateSession(selectedSession)"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Terminate Confirmation Dialog -->
    <q-dialog v-model="showTerminateDialog" persistent>
      <q-card dark>
        <q-card-section class="row items-center">
          <q-avatar icon="mdi-alert" color="negative" text-color="white" />
          <span class="q-ml-sm">{{ terminateMessage }}</span>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('sessionsPage.cancel')" color="grey-7" v-close-popup />
          <q-btn
            flat
            :label="$t('sessionsPage.terminate')"
            color="negative"
            @click="executeTerminate"
            :loading="terminating"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import { formatLongDuration, formatTime } from 'src/composables/useMediaFormatters'
import { useInterval } from 'src/composables/useInterval'
const { t } = useI18n()

// Data
const loading = ref(false)
const cleanupLoading = ref(false)
const sessions = ref([])
const deviceSessions = ref([])
const stats = ref({ total: 0, active: 0 })

// Dialogs
const showDetailsDialog = ref(false)
const showTerminateDialog = ref(false)
const selectedSession = ref(null)
const sessionContract = ref(null)
const sessionContractLoading = ref(false)
const sessionContractError = ref(null)
const terminateMode = ref('single') // 'single' or 'all'
const terminateMessage = ref('')
const terminating = ref(false)

// Auto-refresh every 10 seconds
const { start: startAutoRefresh } = useInterval(() => loadSessions(), 10000)

// Table columns
const columns = computed(() => [
  {
    name: 'user',
    label: t('sessionsPage.colUser'),
    field: 'user_name',
    align: 'left',
    sortable: true,
  },
  {
    name: 'content',
    label: t('sessionsPage.colContent'),
    field: 'content_title',
    align: 'left',
    sortable: true,
  },
  {
    name: 'codecs',
    label: t('sessionsPage.colTranscoding'),
    field: 'video_codec',
    align: 'left',
  },
  {
    name: 'duration',
    label: t('sessionsPage.colDuration'),
    field: 'duration_seconds',
    align: 'left',
    sortable: true,
  },
  {
    name: 'progress',
    label: t('sessionsPage.colProgress'),
    field: 'transcode_progress',
    align: 'left',
  },
  {
    name: 'status',
    label: t('sessionsPage.colStatus'),
    field: 'is_active',
    align: 'center',
    sortable: true,
  },
  {
    name: 'actions',
    label: t('sessionsPage.colActions'),
    field: 'actions',
    align: 'center',
  },
])

const deviceSessionColumns = computed(() => [
  {
    name: 'device',
    label: t('sessionsPage.colDevice'),
    field: 'device_name',
    align: 'left',
    sortable: true,
  },
  {
    name: 'nowPlaying',
    label: t('sessionsPage.colNowPlaying'),
    field: 'current_media_title',
    align: 'left',
    sortable: true,
  },
  {
    name: 'state',
    label: t('sessionsPage.colState'),
    field: 'playback_state',
    align: 'center',
    sortable: true,
  },
  {
    name: 'actions',
    label: t('sessionsPage.colActions'),
    field: 'actions',
    align: 'center',
  },
])

// Computed
const uniqueUsers = computed(
  () => new Set(sessions.value.map((s) => s.user_guid).filter(Boolean)).size,
)

// Field descriptors driving the session-details dialog. Each entry pulls
// a value out of the selectedSession object (with optional formatting and
// fallback) so the template renders one q-item per row in a v-for instead
// of fourteen near-identical handwritten blocks.
// Functions reference top-level helpers (formatTime, formatLongDuration,
// formatDateTime) which are defined further down — JS hoisting keeps this
// safe because the array is only iterated when a session is selected.
const detailFields = computed(() => [
  {
    key: 'fieldSessionId',
    value: selectedSession.value?.session_id || selectedSession.value?.device_id,
    code: true,
  },
  { key: 'fieldContainerId', value: selectedSession.value?.container_id || '-', code: true },
  { key: 'fieldUser', value: selectedSession.value?.user_name || t('sessionsPage.anonymous') },
  { key: 'fieldContent', value: selectedSession.value?.content_title || t('sessionsPage.unknown') },
  { key: 'fieldContentType', value: selectedSession.value?.content_type },
  { key: 'fieldVideoCodec', value: selectedSession.value?.video_codec },
  { key: 'fieldAudioCodec', value: selectedSession.value?.audio_codec },
  {
    key: 'fieldVideoBitrate',
    value: selectedSession.value?.video_bitrate || t('sessionsPage.crfMode'),
  },
  { key: 'fieldAudioBitrate', value: selectedSession.value?.audio_bitrate },
  {
    key: 'fieldResolution',
    value: selectedSession.value?.resolution || t('sessionsPage.original'),
  },
  { key: 'fieldStartPosition', value: formatTime(selectedSession.value?.start_position) },
  { key: 'fieldStartedAt', value: formatDateTime(selectedSession.value?.started_at) },
  { key: 'fieldLastAccessed', value: formatDateTime(selectedSession.value?.last_accessed_at) },
  { key: 'fieldDuration', value: formatLongDuration(selectedSession.value?.duration_seconds) },
])
const capabilityCommands = computed(() => sessionContract.value?.capabilities?.supported_commands || [])
const recentCommands = computed(() => sessionContract.value?.recent_commands || [])
const nowPlayingSummary = computed(() => {
  const nowPlaying = sessionContract.value?.now_playing
  if (!nowPlaying) return t('sessionsPage.nothingPlaying')
  const parts = [
    nowPlaying.media_title || t('sessionsPage.unknown'),
    nowPlaying.playback_state,
    `${formatTime(nowPlaying.position_seconds || 0)} / ${formatTime(nowPlaying.duration_seconds || 0)}`,
  ].filter(Boolean)
  return parts.join(' · ')
})
const queueSummary = computed(() => {
  const queueState = sessionContract.value?.queue_state
  const items = queueState?.items || []
  if (!items.length) return t('sessionsPage.queueEmpty')
  const currentIndex = queueState.current_index ?? queueState.start_index ?? 0
  return t('sessionsPage.queueSummary', { count: items.length, index: currentIndex + 1 })
})

// Methods
const loadSessions = async () => {
  loading.value = true
  try {
    const [sessionsResult, deviceSessionsResult] = await Promise.allSettled([
      api.get('/api/sessions'),
      api.get('/api/devices/sessions/active'),
    ])
    if (sessionsResult.status === 'fulfilled') {
      const response = sessionsResult.value
      sessions.value = response.data.sessions || []
      stats.value = {
        total: response.data.total || 0,
        active: response.data.active_count || 0,
      }
    } else {
      logger.error('Failed to load transcoding sessions:', sessionsResult.reason)
    }
    if (deviceSessionsResult.status === 'fulfilled') {
      deviceSessions.value = deviceSessionsResult.value.data.items || []
    } else {
      logger.error('Failed to load device sessions:', deviceSessionsResult.reason)
      deviceSessions.value = []
    }
  } catch (error) {
    logger.error('Failed to load sessions:', error)
  } finally {
    loading.value = false
  }
}

const getUserInitials = (session) => {
  if (session.user_name) {
    return session.user_name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2)
  }
  return '?'
}

// Single source of truth for status presentation. Evaluated top-down so
// the more specific failure / orphan states win over the generic active
// flag. Returns the matching entry's color, icon and label key.
const STATUS_RULES = [
  {
    match: (s) => s.status === 'failed',
    color: 'negative',
    icon: 'mdi-alert-circle',
    key: 'sessionsPage.failed',
  },
  {
    match: (s) => s.status === 'restarting',
    color: 'warning',
    icon: 'mdi-restart',
    key: 'sessionsPage.restarting',
  },
  {
    match: (s) => s.container_status === 'running',
    color: 'positive',
    icon: 'mdi-play-circle',
    key: 'sessionsPage.active',
  },
  {
    match: (s) => s.container_status === 'not_found',
    color: 'grey',
    icon: 'mdi-help-circle',
    key: 'sessionsPage.orphaned',
  },
  {
    match: (s) => s.is_active,
    color: 'positive',
    icon: 'mdi-play-circle',
    key: 'sessionsPage.active',
  },
]
const FALLBACK_STATUS = { color: 'grey', icon: 'mdi-stop-circle', key: 'sessionsPage.inactive' }

const statusInfo = (session) => STATUS_RULES.find((r) => r.match(session)) || FALLBACK_STATUS

// Convenience wrapper that turns a status rule into ready-to-spread
// q-chip props (so the template doesn't have to call statusInfo three
// times for color, icon and label).
const statusChipProps = (session) => {
  const info = statusInfo(session)
  return { color: info.color, icon: info.icon, label: t(info.key) }
}

const CONTENT_ICONS = {
  movie: 'mdi-movie',
  episode: 'mdi-television',
  music: 'mdi-music',
}
const getContentIcon = (type) => CONTENT_ICONS[type] || 'mdi-play-circle'

const formatDateTime = (dateStr) => (dateStr ? new Date(dateStr).toLocaleString() : '-')

const showSessionDetails = (session) => {
  selectedSession.value = session
  sessionContract.value = null
  sessionContractError.value = null
  showDetailsDialog.value = true
  if (session.device_guid) {
    loadDeviceSessionContract(session.device_guid)
  }
}

const showDeviceSessionDetails = (session) => {
  showSessionDetails(session)
}

const loadDeviceSessionContract = async (deviceGuid) => {
  if (!deviceGuid) return
  sessionContractLoading.value = true
  sessionContractError.value = null
  try {
    const response = await api.get(`/api/devices/${deviceGuid}/session`)
    sessionContract.value = response.data
  } catch (error) {
    sessionContract.value = null
    sessionContractError.value = error
    logger.error('Failed to load device session contract:', error)
  } finally {
    sessionContractLoading.value = false
  }
}

const confirmTerminateSession = (session) => {
  selectedSession.value = session
  terminateMode.value = 'single'
  terminateMessage.value = t('sessionsPage.confirmTerminateSingle', {
    content: session.content_title || t('sessionsPage.unknown'),
  })
  showTerminateDialog.value = true
  showDetailsDialog.value = false
}

const confirmTerminateAll = () => {
  terminateMode.value = 'all'
  terminateMessage.value = t('sessionsPage.confirmTerminateAll', { count: sessions.value.length })
  showTerminateDialog.value = true
}

const executeTerminate = async () => {
  terminating.value = true
  try {
    if (terminateMode.value === 'all') {
      await api.delete('/api/sessions')
    } else if (selectedSession.value) {
      await api.delete(`/api/sessions/${selectedSession.value.session_id}`)
    }
    showTerminateDialog.value = false
    await loadSessions()
  } catch (error) {
    logger.error('Failed to terminate session:', error)
  } finally {
    terminating.value = false
  }
}

const runCleanup = async () => {
  cleanupLoading.value = true
  try {
    await api.post('/api/sessions/cleanup')

    // Refresh sessions list
    await loadSessions()
  } catch (error) {
    logger.error('Cleanup failed:', error)
  } finally {
    cleanupLoading.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadSessions()
  startAutoRefresh()
})
</script>

<style scoped>
code {
  background-color: rgba(0, 0, 0, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 0.85em;
  word-break: break-all;
}

.q-dark code {
  background-color: rgba(255, 255, 255, 0.1);
}
</style>
