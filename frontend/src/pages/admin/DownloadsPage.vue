<template>
  <q-page class="q-pa-md q-pa-md-lg">
    <!-- Header -->
    <div class="row items-start justify-between q-mb-md">
      <div>
        <div class="text-h4">{{ $t('adminDownloads.title') }}</div>
        <div class="text-caption text-grey-6 q-mt-xs">{{ $t('adminDownloads.subtitle') }}</div>
      </div>
      <div class="row items-center q-gutter-sm">
        <q-chip dense outline icon="mdi-autorenew" class="text-grey-5">
          {{ $t('adminDownloads.autoRefresh') }}
        </q-chip>
        <q-btn flat dense round icon="mdi-refresh" :loading="loading" @click="refreshAll">
          <q-tooltip>{{ $t('adminDownloads.refresh') }}</q-tooltip>
        </q-btn>
      </div>
    </div>

    <!-- Control bar -->
    <q-card class="admin-card q-mb-md" flat>
      <q-card-section class="row items-center q-col-gutter-md q-py-sm">
        <div class="col-auto">
          <q-btn
            unelevated
            no-caps
            dense
            :icon="queuePaused ? 'mdi-play' : 'mdi-pause'"
            :color="queuePaused ? 'positive' : 'warning'"
            :label="
              queuePaused
                ? $t('adminDownloads.queue.resumeAll')
                : $t('adminDownloads.queue.pauseAll')
            "
            :loading="queueBusy"
            @click="toggleQueue"
          />
        </div>

        <div class="col-auto row items-center no-wrap">
          <q-input
            v-model.number="speedLimitKbps"
            :label="$t('adminDownloads.queue.speedLimit')"
            type="number"
            min="0"
            outlined
            dark
            dense
            style="width: 138px"
            @keyup.enter="applySpeedLimit"
          />
          <q-btn
            flat
            dense
            icon="mdi-check"
            color="primary"
            class="q-ml-xs"
            :loading="speedBusy"
            @click="applySpeedLimit"
          >
            <q-tooltip>{{ $t('adminDownloads.queue.applyLimit') }}</q-tooltip>
          </q-btn>
        </div>

        <q-space />

        <div class="col-auto row items-center q-gutter-sm">
          <span class="metric" :class="queuePaused ? 'text-grey-6' : 'text-info'">
            <q-icon name="mdi-speedometer" size="16px" class="q-mr-xs" />
            {{ formatSpeed(overview?.speed_bps) }}
          </span>
          <q-separator vertical inset />
          <span class="metric text-grey-4">
            {{ overview?.counts?.downloading ?? 0 }} {{ $t('adminDownloads.queue.active') }}
          </span>
          <span class="metric text-grey-4">
            {{ overview?.counts?.queued ?? 0 }} {{ $t('adminDownloads.queue.queued') }}
          </span>
          <q-separator vertical inset />
          <q-chip
            v-for="client in downloaders"
            :key="client.label"
            dense
            outline
            :icon="client.reachable ? 'mdi-check-circle' : 'mdi-alert-circle'"
            :color="client.reachable ? 'grey-5' : 'negative'"
          >
            {{ client.label }}
            <q-tooltip v-if="!client.reachable">{{ client.error }}</q-tooltip>
          </q-chip>
          <q-chip
            v-if="queuePaused"
            dense
            color="warning"
            text-color="white"
            icon="mdi-pause-circle"
            :label="$t('adminDownloads.queue.paused')"
          />
        </div>
      </q-card-section>
    </q-card>

    <!-- Downloads table -->
    <q-card class="admin-card" flat>
      <q-card-section class="row items-center q-col-gutter-md q-py-sm">
        <div class="col-auto">
          <q-btn-toggle
            v-model="statusFilter"
            :options="statusTabs"
            dense
            no-caps
            unelevated
            toggle-color="primary"
            color="grey-9"
            text-color="grey-4"
          />
        </div>

        <q-space />

        <div class="col-12 col-md-3">
          <q-input
            v-model="search"
            :placeholder="$t('common.search')"
            outlined
            dark
            dense
            clearable
          >
            <template v-slot:prepend>
              <q-icon name="mdi-magnify" size="xs" />
            </template>
          </q-input>
        </div>
      </q-card-section>

      <q-separator />

      <q-table
        flat
        dark
        dense
        class="admin-table download-table"
        :rows="rows"
        :columns="columns"
        :loading="loading"
        row-key="guid"
        :rows-per-page-options="[50, 100, 0]"
        :pagination="{ rowsPerPage: 50 }"
      >
        <template v-slot:body-cell-status="props">
          <q-td :props="props" class="status-cell">
            <span class="status-dot" :class="`dot-${statusKey(props.value)}`" />
          </q-td>
        </template>

        <template v-slot:body-cell-display_title="props">
          <q-td :props="props">
            <router-link
              v-if="props.row.media_item_guid"
              :to="`/media/${props.row.media_item_guid}`"
              class="row-title"
            >
              {{ props.row.display_title }}
            </router-link>
            <div v-else class="row-title">{{ props.row.display_title }}</div>
            <div class="row-meta ellipsis">
              <span v-if="getStatusDetail(props.row)" class="text-warning">
                {{ getStatusDetail(props.row) }}
              </span>
              <template v-else>
                <span v-if="showStatusLabel(props.row)">{{ getStatusLabel(props.row.status) }}</span>
                <span v-if="showEpisodeTag(props.row)">
                  S{{ String(props.row.season_number).padStart(2, '0') }}E{{
                    String(props.row.episode_number ?? 0).padStart(2, '0')
                  }}
                </span>
                <span v-if="props.row.started_by_name">
                  {{ props.row.started_by_name }}</span
                >
                <span v-if="props.row.created_at">
                  {{ formatRelativeTime(props.row.created_at) }}</span
                >
              </template>
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-size="props">
          <q-td :props="props" class="num">
            <span v-if="props.row.total_bytes">
              <span v-if="props.row.downloaded_bytes != null" class="text-grey-4">
                {{ formatBytes(props.row.downloaded_bytes) }}
              </span>
              <span v-if="props.row.downloaded_bytes != null" class="text-grey-7"> / </span>
              {{ formatBytes(props.row.total_bytes) }}
            </span>
            <span v-else class="text-grey-7">–</span>
          </q-td>
        </template>

        <template v-slot:body-cell-progress="props">
          <q-td :props="props">
            <div class="row items-center no-wrap">
              <q-linear-progress
                :value="(props.row.progress ?? 0) / 100"
                :color="progressColor(props.row)"
                track-color="grey-9"
                class="col q-mr-sm"
                size="5px"
                rounded
              />
              <span class="num text-caption text-grey-4">
                {{ props.row.progress != null ? Math.round(props.row.progress) : 0 }}%
              </span>
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-speed_bps="props">
          <q-td :props="props" class="num">
            <span :class="props.value > 0 ? 'text-grey-3' : 'text-grey-7'">
              {{ formatSpeed(props.value) }}
            </span>
          </q-td>
        </template>

        <template v-slot:body-cell-eta_seconds="props">
          <q-td :props="props" class="num">
            <span :class="props.value != null ? 'text-grey-4' : 'text-grey-7'">
              {{ formatEta(props.value) }}
            </span>
          </q-td>
        </template>

        <template v-slot:body-cell-actions="props">
          <q-td :props="props">
            <div class="row justify-end no-wrap">
              <q-btn
                v-if="isPausable(props.row)"
                flat
                dense
                round
                icon="mdi-pause"
                color="warning"
                size="sm"
                @click="togglePause(props.row, true)"
              >
                <q-tooltip>{{ $t('common.pause') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="isPaused(props.row)"
                flat
                dense
                round
                icon="mdi-play"
                color="positive"
                size="sm"
                @click="togglePause(props.row, false)"
              >
                <q-tooltip>{{ $t('common.resume') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat
                dense
                round
                icon="mdi-delete-outline"
                color="grey-6"
                size="sm"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </div>
          </q-td>
        </template>

        <template v-slot:no-data>
          <div class="column items-center q-pa-xl text-center">
            <q-icon name="mdi-tray-remove" size="40px" class="text-grey-8 q-mb-sm" />
            <div class="text-grey-5">{{ $t('adminDownloads.emptyTitle') }}</div>
            <div class="text-caption text-grey-7">{{ $t('adminDownloads.emptyHint') }}</div>
          </div>
        </template>
      </q-table>
    </q-card>

    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminDownloads.confirmDelete')"
      :loading="deleting"
      @confirm="deleteDownload"
    />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  formatFileSize as formatBytes,
  formatRelativeTime,
  formatSpeed,
} from 'src/composables/useMediaFormatters'
import {
  listDownloads,
  setDownloadPaused,
  deleteDownload as deleteDownloadRequest,
  getDownloadOverview,
  pauseDownloadQueue,
  resumeDownloadQueue,
  setDownloadSpeedLimit,
} from 'src/services/acquisitionAdminService'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()

// Every download row, already merged with the live queue state. The table is the
// page, so a row has to show what is happening *now* - not a value stored five
// minutes ago when the row was written.
const downloads = ref([])
const loading = ref(false)
const search = ref('')
const statusFilter = ref(null)
const showDeleteDialog = ref(false)
const deleting = ref(false)
const selectedDownload = ref(null)

// --- queue control ---
const overview = ref(null)
const queueBusy = ref(false)
const speedBusy = ref(false)
const speedLimitKbps = ref(0)

const queuePaused = computed(() => overview.value?.paused === true)
const downloaders = computed(() => overview.value?.downloaders || [])

// Live jobs keyed by downloader job id and, as a fallback, by release name -
// older rows predate external_id, and a name match still beats no live data.
const liveJobs = computed(() => {
  const map = new Map()
  for (const job of overview.value?.jobs || []) {
    if (job.id) map.set(String(job.id), job)
    if (job.name) map.set(`name:${job.name}`, job)
  }
  return map
})

const STATUS_ORDER = {
  downloading: 0,
  queued: 1,
  pending: 2,
  paused: 3,
  failed: 4,
  completed: 5,
  imported: 6,
}

const merged = computed(() =>
  downloads.value.map((row) => {
    const live =
      (row.external_id && liveJobs.value.get(String(row.external_id))) ||
      liveJobs.value.get(`name:${row.title}`)

    const progress = live?.progress ?? row.progress
    const speed = live?.speed_bps ?? row.speed_bps
    const total = live?.total_bytes || row.size_bytes || null
    let done = live?.downloaded_bytes ?? null
    if (done == null && total && progress != null) {
      done = Math.round((total * progress) / 100)
    }
    // ETA only while something actually moves - a stalled job has no estimate.
    const eta = speed > 0 && total && done != null ? (total - done) / speed : null

    return {
      ...row,
      live: Boolean(live),
      progress,
      speed_bps: speed,
      total_bytes: total,
      downloaded_bytes: done,
      eta_seconds: eta,
    }
  }),
)

// Active first, then newest: the rows an operator opens the page for are always
// on top, no matter how the client-side sorting is configured.
const rows = computed(() => {
  const needle = search.value.trim().toLowerCase()
  const filter = statusFilter.value
  return merged.value
    .filter((row) => {
      if (filter && statusKey(row.status) !== filter) return false
      if (!needle) return true
      return (
        (row.display_title || '').toLowerCase().includes(needle) ||
        (row.title || '').toLowerCase().includes(needle)
      )
    })
    .sort((a, b) => {
      const byStatus =
        (STATUS_ORDER[statusKey(a.status)] ?? 9) - (STATUS_ORDER[statusKey(b.status)] ?? 9)
      if (byStatus !== 0) return byStatus
      return new Date(b.created_at || 0) - new Date(a.created_at || 0)
    })
})

// Counts live next to the tab label: "which tab do I need" is answered before
// clicking instead of after.
const statusCounts = computed(() => {
  const counts = {}
  for (const row of merged.value) {
    const key = statusKey(row.status)
    counts[key] = (counts[key] || 0) + 1
  }
  return counts
})

const statusTabs = computed(() => {
  const tab = (value, label) => ({
    value,
    label: `${label} ${value ? statusCounts.value[value] || 0 : merged.value.length}`,
  })
  return [
    tab(null, t('adminDownloads.tabs.all')),
    tab('downloading', t('adminDownloads.tabs.active')),
    tab('queued', t('adminDownloads.tabs.queued')),
    tab('failed', t('adminDownloads.tabs.failed')),
    tab('imported', t('adminDownloads.tabs.imported')),
  ]
})

const columns = computed(() => [
  {
    name: 'status',
    label: '',
    align: 'center',
    field: 'status',
    style: 'width: 26px',
  },
  {
    name: 'display_title',
    required: true,
    label: t('adminDownloads.columns.title'),
    align: 'left',
    field: 'display_title',
  },
  {
    name: 'size',
    label: t('adminDownloads.columns.size'),
    align: 'right',
    field: 'total_bytes',
    style: 'width: 150px',
  },
  {
    name: 'progress',
    label: t('adminDownloads.columns.progress'),
    align: 'left',
    field: 'progress',
    style: 'width: 190px',
  },
  {
    name: 'speed_bps',
    label: t('adminDownloads.columns.speed'),
    align: 'right',
    field: 'speed_bps',
    style: 'width: 100px',
  },
  {
    name: 'eta_seconds',
    label: t('adminDownloads.columns.eta'),
    align: 'right',
    field: 'eta_seconds',
    style: 'width: 90px',
  },
  {
    name: 'actions',
    label: '',
    align: 'right',
    field: 'actions',
    style: 'width: 110px',
  },
])

const loadOverview = async () => {
  try {
    overview.value = await getDownloadOverview()
    const limit = downloaders.value.find((d) => d.speed_limit_kbps)?.speed_limit_kbps
    if (limit && !speedBusy.value) speedLimitKbps.value = limit
  } catch (error) {
    logger.error('Failed to load download overview:', error)
  }
}

const toggleQueue = async () => {
  queueBusy.value = true
  try {
    if (queuePaused.value) await resumeDownloadQueue()
    else await pauseDownloadQueue()
    await loadOverview()
  } catch (error) {
    logger.error('Failed to toggle download queue:', error)
  } finally {
    queueBusy.value = false
  }
}

const applySpeedLimit = async () => {
  speedBusy.value = true
  try {
    await setDownloadSpeedLimit(Number(speedLimitKbps.value) || 0)
    await loadOverview()
  } catch (error) {
    logger.error('Failed to set speed limit:', error)
  } finally {
    speedBusy.value = false
  }
}

const loadDownloads = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    downloads.value = (await listDownloads()) || []
  } catch (error) {
    logger.error('Failed to load downloads:', error)
  } finally {
    if (!silent) loading.value = false
  }
}

const refreshAll = () => Promise.all([loadDownloads(), loadOverview()])

const statusKey = (status) => (status || '').toLowerCase()

const isPaused = (download) => statusKey(download?.status) === 'paused'
const isPausable = (download) => ['downloading', 'queued'].includes(statusKey(download?.status))

const showEpisodeTag = (row) => row.show_title && row.season_number != null

// For running rows the rate and ETA already say what is going on; for settled
// rows the coloured dot needs a word next to it.
const showStatusLabel = (row) => !['downloading', 'queued'].includes(statusKey(row.status))

const getStatusLabel = (status) => t(`adminDownloads.statuses.${statusKey(status)}`, status)

const progressColor = (row) => {
  const key = statusKey(row.status)
  if (key === 'failed') return 'negative'
  if (row.progress >= 100 || key === 'imported' || key === 'completed') return 'positive'
  return row.live ? 'info' : 'grey-7'
}

// Seconds -> "8 Min" / "1 Std 20 Min"; the exact second is noise on a page that
// refreshes every five seconds.
const formatEta = (seconds) => {
  if (seconds == null || !Number.isFinite(seconds)) return '–'
  const total = Math.round(seconds)
  if (total < 60) return `${total} s`
  const minutes = Math.round(total / 60)
  if (minutes < 60) return `${minutes} Min`
  const hours = Math.floor(minutes / 60)
  return `${hours} Std ${String(minutes % 60).padStart(2, '0')}`
}

const togglePause = async (download, pause) => {
  try {
    await setDownloadPaused(download.guid, pause)
    await refreshAll()
  } catch (error) {
    logger.error(`Failed to ${pause ? 'pause' : 'resume'} download:`, error)
  }
}

const STATUS_DETAIL_KEYS = {
  preparing: 'adminDownloads.statusDetails.preparing',
  searching: 'adminDownloads.statusDetails.searching',
  retrying_release: 'adminDownloads.statusDetails.retryingRelease',
  importing: 'adminDownloads.statusDetails.importing',
}

const getStatusDetail = (download) => {
  const key = statusKey(download?.status)
  if (key === 'failed' || key === 'cancelled') {
    return download?.error_reason || download?.status_detail || t('adminDownloads.statuses.failed')
  }

  const explicitDetail = download?.status_detail
  if (explicitDetail) return explicitDetail

  const phase = (download?.status_phase || '').toLowerCase()
  const detailKey = STATUS_DETAIL_KEYS[phase]
  return detailKey ? t(detailKey) : ''
}

const confirmDelete = (download) => {
  selectedDownload.value = download
  showDeleteDialog.value = true
}

const deleteDownload = async () => {
  if (!selectedDownload.value) return

  deleting.value = true
  try {
    await deleteDownloadRequest(selectedDownload.value.guid)
    showDeleteDialog.value = false
    selectedDownload.value = null
    await refreshAll()
  } catch (error) {
    logger.error('Failed to delete download:', error)
  } finally {
    deleting.value = false
  }
}

const POLL_MS = 5000
let pollTimer = null
let rowTimer = null

onMounted(() => {
  refreshAll()
  // Live queue every 5 s, the row list less often: statuses change slowly while
  // rate/progress change constantly.
  pollTimer = setInterval(loadOverview, POLL_MS)
  rowTimer = setInterval(() => loadDownloads(true), POLL_MS * 6)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (rowTimer) clearInterval(rowTimer)
})
</script>

<style scoped lang="scss">
.row-title {
  color: inherit;
  text-decoration: none;
  font-weight: 500;

  &:hover {
    color: var(--q-primary);
  }
}

.row-meta {
  font-size: 0.7rem;
  color: #8b8b8b;
  max-width: 100%;

  span + span::before {
    content: ' · ';
    color: #555;
  }
}

// Numbers in a live table must not jitter: equal-width digits keep the columns
// from shifting on every poll.
.num {
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
  white-space: nowrap;
}

.status-cell {
  padding-right: 0 !important;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #666;
}

.dot-downloading {
  background: var(--q-info);
  box-shadow: 0 0 0 3px rgba(49, 161, 222, 0.18);
}
.dot-queued,
.dot-pending {
  background: #8a8a8a;
}
.dot-paused {
  background: var(--q-warning);
}
.dot-failed {
  background: var(--q-negative);
}
.dot-cancelled {
  background: #5a5a5a;
}
.dot-completed,
.dot-imported {
  background: var(--q-positive);
}

.metric {
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

// Sticky header: with 50 rows per page the column labels have to stay readable
// while scrolling.
.download-table :deep(thead tr) {
  th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: #1d1d1d !important;
  }
}
</style>
