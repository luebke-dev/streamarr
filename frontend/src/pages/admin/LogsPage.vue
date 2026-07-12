<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminLogs.title') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md items-end">
          <div class="col-12 col-md-5">
            <q-select
              v-model="selectedSession"
              :options="sessionOptions"
              :label="$t('adminLogs.selectSession')"
              outlined
              dense
              emit-value
              map-options
              clearable
              :loading="sessionsLoading"
            >
              <template v-slot:prepend><q-icon name="mdi-server" /></template>
              <template v-slot:option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section avatar>
                    <q-avatar
                      :color="scope.opt.active ? 'positive' : 'grey-6'"
                      text-color="white"
                      size="28px"
                    >
                      <q-icon :name="scope.opt.active ? 'mdi-play' : 'mdi-stop'" size="14px" />
                    </q-avatar>
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ scope.opt.label }}</q-item-label>
                    <q-item-label caption
                      >{{ scope.opt.user }} &middot; {{ scope.opt.codec }}</q-item-label
                    >
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
          </div>
          <div class="col-6 col-md-3">
            <q-select
              v-model="tailLines"
              :options="tailOptions"
              :label="$t('adminLogs.lines')"
              outlined
              dense
              emit-value
              map-options
            />
          </div>
          <div class="col-6 col-md-4 row q-gutter-sm justify-end">
            <q-btn
              color="primary"
              icon="mdi-refresh"
              :label="$t('adminLogs.loadLogs')"
              :loading="logsLoading"
              :disable="!selectedSession"
              @click="loadLogs"
              no-caps
            />
            <q-toggle v-model="autoRefresh" :label="$t('adminLogs.autoRefresh')" />
          </div>
        </div>
      </q-card-section>

      <!-- Log Output -->
      <q-separator />
      <q-card-section class="q-pa-none">
        <div v-if="!selectedSession" class="text-center text-grey-5 q-pa-xl">
          <q-icon name="mdi-text-box-outline" size="3rem" class="q-mb-md" />
          <div>{{ $t('adminLogs.selectSessionHint') }}</div>
        </div>
        <div v-else-if="logsLoading && !logs" class="text-center q-pa-xl">
          <q-spinner color="primary" size="2rem" />
        </div>
        <div v-else-if="logsError" class="text-center text-negative q-pa-xl">
          <q-icon name="mdi-alert-circle" size="2rem" class="q-mb-sm" />
          <div>{{ logsError }}</div>
        </div>
        <pre v-else class="log-output" ref="logContainer">{{ logs || $t('adminLogs.noLogs') }}</pre>
      </q-card-section>
    </q-card>

    <q-card flat bordered class="q-mt-md">
      <q-card-section>
        <div class="text-h6 q-mb-md">{{ $t('adminLogs.activityLogs') }}</div>
        <div class="row q-col-gutter-md items-end">
          <div class="col-12 col-md-2">
            <q-input v-model="activityFilters.event_type" :label="$t('adminLogs.eventType')" outlined dense />
          </div>
          <div class="col-12 col-md-2">
            <q-select
              v-model="activityFilters.severity"
              :options="severityOptions"
              :label="$t('adminLogs.severity')"
              outlined
              dense
              clearable
              emit-value
              map-options
            />
          </div>
          <div class="col-12 col-md-2">
            <q-input v-model="activityFilters.entity_type" :label="$t('adminLogs.entityType')" outlined dense />
          </div>
          <div class="col-12 col-md-2">
            <q-input v-model="activityFilters.min_date" :label="$t('adminLogs.fromDate')" outlined dense type="date" />
          </div>
          <div class="col-12 col-md-2">
            <q-input v-model="activityFilters.max_date" :label="$t('adminLogs.toDate')" outlined dense type="date" />
          </div>
          <div class="col-12 col-md-2">
            <q-btn
              color="primary"
              icon="mdi-filter"
              :label="$t('common.search')"
              :loading="activityLoading"
              class="full-width"
              @click="loadActivityLogs"
              no-caps
            />
          </div>
        </div>
      </q-card-section>
      <q-table
        :rows="activityLogs"
        :columns="activityColumns"
        row-key="guid"
        :loading="activityLoading"
        flat
        bordered
        dark
        :pagination="{ rowsPerPage: 20 }"
      >
        <template v-slot:body-cell-severity="props">
          <q-td :props="props">
            <q-chip
              size="sm"
              :color="severityColor(props.row.severity)"
              text-color="white"
              :label="props.row.severity"
            />
          </q-td>
        </template>
        <template v-slot:body-cell-created_at="props">
          <q-td :props="props">{{ formatDateTime(props.row.created_at) }}</q-td>
        </template>
      </q-table>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { getSessions, getSessionLogs, getActivityLogs } from 'src/services/systemAdminService'
import { useInterval } from 'src/composables/useInterval'

const { t } = useI18n()

const sessionsLoading = ref(false)
const logsLoading = ref(false)
const sessions = ref([])
const selectedSession = ref(null)
const logs = ref('')
const logsError = ref(null)
const tailLines = ref(200)
const autoRefresh = ref(false)
const logContainer = ref(null)
const activityLoading = ref(false)
const activityLogs = ref([])
const activityFilters = ref({
  event_type: '',
  severity: null,
  entity_type: '',
  min_date: '',
  max_date: '',
})

const { start: startAutoRefresh, stop: stopAutoRefresh } = useInterval(() => {
  if (selectedSession.value) loadLogs()
}, 3000)

const tailOptions = [
  { value: 50, label: '50' },
  { value: 100, label: '100' },
  { value: 200, label: '200' },
  { value: 500, label: '500' },
  { value: 1000, label: '1000' },
]
const severityOptions = [
  { value: 'info', label: 'info' },
  { value: 'warning', label: 'warning' },
  { value: 'error', label: 'error' },
]

const activityColumns = computed(() => [
  {
    name: 'created_at',
    label: t('adminLogs.createdAt'),
    field: 'created_at',
    align: 'left',
    sortable: true,
  },
  {
    name: 'severity',
    label: t('adminLogs.severity'),
    field: 'severity',
    align: 'left',
  },
  {
    name: 'event_type',
    label: t('adminLogs.eventType'),
    field: 'event_type',
    align: 'left',
    sortable: true,
  },
  {
    name: 'entity_type',
    label: t('adminLogs.entityType'),
    field: 'entity_type',
    align: 'left',
  },
  {
    name: 'message',
    label: t('adminLogs.message'),
    field: 'message',
    align: 'left',
  },
])

const sessionOptions = computed(() =>
  sessions.value.map((s) => ({
    value: s.session_id,
    label: s.content_title || s.session_id.slice(0, 8),
    user: s.user_name || t('adminLogs.unknownUser'),
    codec: `${s.video_codec}/${s.audio_codec}`,
    active: s.is_active,
  })),
)

const loadSessions = async () => {
  sessionsLoading.value = true
  try {
    const res = await getSessions()
    sessions.value = res.sessions || []
  } catch (error) {
    logger.error('Error loading sessions:', error)
  } finally {
    sessionsLoading.value = false
  }
}

const loadLogs = async () => {
  if (!selectedSession.value) return
  logsLoading.value = true
  logsError.value = null
  try {
    const res = await getSessionLogs(selectedSession.value, { tail_lines: tailLines.value })
    logs.value = res.logs || ''
    await nextTick()
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  } catch (error) {
    logger.error('Error loading logs:', error)
    logsError.value = error.response?.data?.detail || error.message
  } finally {
    logsLoading.value = false
  }
}

const loadActivityLogs = async () => {
  activityLoading.value = true
  try {
    const params = {
      event_type: activityFilters.value.event_type || undefined,
      severity: activityFilters.value.severity || undefined,
      entity_type: activityFilters.value.entity_type || undefined,
      min_date: activityFilters.value.min_date || undefined,
      max_date: activityFilters.value.max_date || undefined,
      per_page: 100,
    }
    const res = await getActivityLogs(params)
    activityLogs.value = res.items || []
  } catch (error) {
    logger.error('Error loading activity logs:', error)
  } finally {
    activityLoading.value = false
  }
}

const severityColor = (severity) => {
  if (severity === 'error') return 'negative'
  if (severity === 'warning') return 'warning'
  return 'info'
}

const formatDateTime = (value) => (value ? new Date(value).toLocaleString() : '-')

watch(autoRefresh, (val) => {
  if (val) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
})

watch(selectedSession, (val) => {
  logs.value = ''
  logsError.value = null
  if (val) loadLogs()
})

onMounted(() => {
  loadSessions()
  loadActivityLogs()
})
</script>

<style lang="scss" scoped>
.log-output {
  margin: 0;
  padding: 16px;
  background: #0d1117;
  color: #c9d1d9;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.8rem;
  line-height: 1.5;
  overflow: auto;
  max-height: 70vh;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
