<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminDownloads.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminDownloads.subtitle') }}</div>

    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="row items-center q-col-gutter-md">
          <div class="col-auto">
            <q-btn
              :icon="queuePaused ? 'mdi-play' : 'mdi-pause'"
              :color="queuePaused ? 'positive' : 'warning'"
              :label="
                queuePaused
                  ? $t('adminDownloads.queue.resumeAll', 'Resume all')
                  : $t('adminDownloads.queue.pauseAll', 'Pause all')
              "
              :loading="queueBusy"
              unelevated
              @click="toggleQueue"
            />
          </div>

          <div class="col-auto">
            <q-chip
              :color="queuePaused ? 'warning' : 'positive'"
              text-color="white"
              :icon="queuePaused ? 'mdi-pause-circle' : 'mdi-download-network'"
              dense
            >
              {{
                queuePaused
                  ? $t('adminDownloads.queue.paused', 'Queue paused')
                  : $t('adminDownloads.queue.running', 'Queue running')
              }}
            </q-chip>
          </div>

          <div class="col-auto">
            <q-chip dense outline icon="mdi-speedometer">
              {{ formatSpeed(overview?.speed_bps) }}
            </q-chip>
          </div>

          <div class="col-auto">
            <q-chip dense outline icon="mdi-tray-full">
              {{ overview?.counts?.downloading || 0 }}
              {{ $t('adminDownloads.queue.active', 'active') }} ·
              {{ overview?.counts?.queued || 0 }}
              {{ $t('adminDownloads.queue.queued', 'queued') }}
            </q-chip>
          </div>

          <q-space />

          <div class="col-12 col-md-4">
            <div class="row items-center no-wrap q-gutter-sm">
              <q-input
                v-model.number="speedLimitKbps"
                :label="$t('adminDownloads.queue.speedLimit', 'Limit (KB/s)')"
                type="number"
                min="0"
                outlined
                dark
                dense
                class="col"
                :hint="$t('adminDownloads.queue.speedLimitHint', '0 = unlimited')"
                @keyup.enter="applySpeedLimit"
              />
              <q-btn
                flat
                dense
                icon="mdi-check"
                color="primary"
                :loading="speedBusy"
                @click="applySpeedLimit"
              >
                <q-tooltip>{{ $t('common.apply', 'Apply') }}</q-tooltip>
              </q-btn>
            </div>
          </div>
        </div>

        <div v-if="jobRows.length" class="q-mt-md">
          <q-linear-progress
            v-for="job in jobRows"
            :key="job.id"
            :value="job.progress / 100"
            size="18px"
            rounded
            :color="job.status === 'downloading' ? 'primary' : 'grey-7'"
            class="q-mb-sm"
          >
            <div class="row items-center justify-between q-px-sm text-caption">
              <span class="ellipsis" style="max-width: 55%">{{ job.name }}</span>
              <span>
                {{ Math.round(job.progress) }}% ·
                {{ formatSpeed(job.speed_bps) }} ·
                {{ formatBytes(job.downloaded_bytes) }} /
                {{ formatBytes(job.total_bytes) }}
              </span>
            </div>
          </q-linear-progress>
        </div>
      </q-card-section>
    </q-card>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model="search"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
              @update:model-value="debouncedSearch"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>

          <div class="col-12 col-md-6">
            <q-select
              v-model="statusFilter"
              :options="statusOptions"
              :label="$t('adminDownloads.filterByStatus')"
              outlined
              dark
              dense
              emit-value
              map-options
              clearable
              @update:model-value="loadDownloads"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-filter" />
              </template>
            </q-select>
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          :rows="downloads"
          :columns="columns"
          :loading="loading"
          row-key="guid"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
        >
          <template v-slot:body-cell-type="props">
            <q-td :props="props">
              <q-icon :name="getTypeIcon(props.value)" size="sm" :color="getTypeColor(props.value)">
                <q-tooltip>{{ props.value }}</q-tooltip>
              </q-icon>
            </q-td>
          </template>

          <template v-slot:body-cell-display_title="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.media_item_guid"
                :to="`/media/${props.row.media_item_guid}`"
                class="text-primary"
                style="text-decoration: none"
              >
                {{ props.row.display_title }}
              </router-link>
              <span v-else>{{ props.row.display_title }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-chip :color="getStatusColor(props.value)" text-color="white" size="sm" dense>
                {{ getStatusLabel(props.value) }}
              </q-chip>
              <div
                v-if="getStatusDetail(props.row)"
                class="download-status-detail text-caption text-grey-5 q-mt-xs"
              >
                {{ getStatusDetail(props.row) }}
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-downloader_name="props">
            <q-td :props="props">
              <div v-if="props.row.downloader_name" class="row items-center no-wrap">
                <q-icon
                  :name="props.row.downloader_type === 'sabnzbd' ? 'mdi-download' : 'mdi-magnet'"
                  size="xs"
                  class="q-mr-xs"
                  :color="props.row.downloader_type === 'sabnzbd' ? 'amber' : 'light-blue'"
                />
                <span>{{ props.row.downloader_name }}</span>
              </div>
              <span v-else class="text-grey">-</span>
            </q-td>
          </template>

          <template v-slot:body-cell-progress="props">
            <q-td :props="props">
              <div v-if="props.value !== null" class="row items-center no-wrap">
                <q-linear-progress
                  :value="props.value / 100"
                  :color="props.value >= 100 ? 'positive' : 'primary'"
                  class="col q-mr-sm"
                  size="8px"
                  rounded
                />
                <span class="text-caption">{{ props.value.toFixed(1) }}%</span>
              </div>
              <span v-else class="text-grey">-</span>
            </q-td>
          </template>

          <template v-slot:body-cell-started_by_name="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.user_guid"
                :to="`/admin/users/${props.row.user_guid}`"
                class="text-primary"
                style="text-decoration: none"
              >
                {{ props.row.started_by_name }}
              </router-link>
              <span v-else>{{ props.row.started_by_name || '-' }}</span>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
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
                <q-tooltip>{{ $t('common.pause', 'Pause') }}</q-tooltip>
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
                <q-tooltip>{{ $t('common.resume', 'Resume') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat
                dense
                round
                icon="mdi-delete"
                color="negative"
                size="sm"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
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
import { debounce } from 'quasar'
import { logger } from 'src/utils/logger'
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
const jobRows = computed(() =>
  (overview.value?.jobs || []).filter((j) => j.status === 'downloading'),
)

const formatBytes = (bytes) => {
  const n = Number(bytes) || 0
  if (n <= 0) return '0 B'
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`
  return `${(n / 1024).toFixed(0)} KB`
}

const loadOverview = async () => {
  try {
    overview.value = await getDownloadOverview()
    const limit = overview.value?.downloaders?.find(
      (d) => d.speed_limit_kbps,
    )?.speed_limit_kbps
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

const statusOptions = computed(() => [
  { label: t('adminDownloads.statuses.pending'), value: 'pending' },
  { label: t('adminDownloads.statuses.queued'), value: 'queued' },
  { label: t('adminDownloads.statuses.downloading'), value: 'downloading' },
  { label: t('adminDownloads.statuses.paused'), value: 'paused' },
  { label: t('adminDownloads.statuses.completed'), value: 'completed' },
  { label: t('adminDownloads.statuses.failed'), value: 'failed' },
  { label: t('adminDownloads.statuses.imported'), value: 'imported' },
])

const columns = computed(() => [
  {
    name: 'type',
    label: t('adminDownloads.columns.type'),
    align: 'center',
    field: 'type',
    sortable: true,
    style: 'width: 40px',
  },
  {
    name: 'display_title',
    required: true,
    label: t('adminDownloads.columns.title'),
    align: 'left',
    field: 'display_title',
    sortable: true,
  },
  {
    name: 'status',
    label: t('adminDownloads.columns.status'),
    align: 'left',
    field: 'status',
    sortable: true,
  },
  {
    name: 'downloader_name',
    label: t('adminDownloads.columns.downloader'),
    align: 'left',
    field: 'downloader_name',
    sortable: true,
    format: (val) => val || '-',
  },
  {
    name: 'progress',
    label: t('adminDownloads.columns.progress'),
    align: 'left',
    field: 'progress',
    sortable: true,
  },
  {
    name: 'speed',
    label: t('adminDownloads.columns.speed', 'Speed'),
    align: 'right',
    field: 'speed_bps',
    sortable: true,
    format: (val) => formatSpeed(val),
  },
  {
    name: 'started_by_name',
    label: t('adminDownloads.columns.startedBy'),
    align: 'left',
    field: 'started_by_name',
    sortable: true,
    format: (val) => val || '-',
  },
  {
    name: 'created_at',
    label: t('adminDownloads.columns.created'),
    align: 'left',
    field: 'created_at',
    sortable: true,
    format: (val) => (val ? new Date(val).toLocaleString() : '-'),
  },
  {
    name: 'actions',
    label: t('common.actions'),
    align: 'center',
    field: 'actions',
  },
])

const loadDownloads = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    downloads.value = await listDownloads()

    // Apply local filtering
    if (search.value) {
      downloads.value = downloads.value.filter((d) =>
        d.display_title.toLowerCase().includes(search.value.toLowerCase()),
      )
    }

    if (statusFilter.value) {
      downloads.value = downloads.value.filter(
        (d) => (d.status || '').toLowerCase() === statusFilter.value,
      )
    }
  } catch (error) {
    logger.error('Failed to load downloads:', error)
  } finally {
    if (!silent) loading.value = false
  }
}

const formatSpeed = (bps) => {
  const n = Number(bps) || 0
  if (n <= 0) return '-'
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB/s`
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB/s`
  return `${n} B/s`
}

const isPaused = (download) => (download?.status || '').toLowerCase() === 'paused'
const isPausable = (download) =>
  ['downloading', 'queued'].includes((download?.status || '').toLowerCase())

const togglePause = async (download, pause) => {
  try {
    await setDownloadPaused(download.guid, pause)
    loadDownloads(true)
  } catch (error) {
    logger.error(`Failed to ${pause ? 'pause' : 'resume'} download:`, error)
  }
}

const debouncedSearch = debounce(() => {
  loadDownloads()
}, 500)

const getTypeIcon = (type) => {
  const t = (type || '').toLowerCase()
  // The backend sends media-type values (MOVIES/SHOWS/GAMES/SONGS/BOOKS) as
  // well as legacy singular forms — map both.
  const icons = {
    movie: 'mdi-movie',
    movies: 'mdi-movie',
    episode: 'mdi-television',
    episodes: 'mdi-television',
    show: 'mdi-television',
    shows: 'mdi-television',
    music: 'mdi-music',
    song: 'mdi-music',
    songs: 'mdi-music',
    game: 'mdi-gamepad-variant',
    games: 'mdi-gamepad-variant',
    book: 'mdi-book',
    books: 'mdi-book',
  }
  return icons[t] || 'mdi-download'
}

const getTypeColor = (type) => {
  const t = (type || '').toLowerCase()
  const colors = {
    movie: 'amber',
    movies: 'amber',
    episode: 'light-blue',
    episodes: 'light-blue',
    show: 'light-blue',
    shows: 'light-blue',
    music: 'pink',
    song: 'pink',
    songs: 'pink',
    game: 'purple',
    games: 'purple',
    book: 'brown',
    books: 'brown',
  }
  return colors[t] || 'grey'
}

const getStatusColor = (status) => {
  const s = (status || '').toLowerCase()
  const colors = {
    queued: 'grey',
    downloading: 'blue',
    paused: 'orange',
    completed: 'green',
    failed: 'red',
    imported: 'teal',
  }
  return colors[s] || 'grey'
}

const getStatusLabel = (status) => {
  const s = (status || '').toLowerCase()
  return t(`adminDownloads.statuses.${s}`, status)
}

const STATUS_DETAIL_KEYS = {
  preparing: 'adminDownloads.statusDetails.preparing',
  searching: 'adminDownloads.statusDetails.searching',
  retrying_release: 'adminDownloads.statusDetails.retryingRelease',
  importing: 'adminDownloads.statusDetails.importing',
}

const getStatusDetail = (download) => {
  const explicitDetail = download?.status_detail || download?.error_reason
  if (explicitDetail) return explicitDetail

  const phase = (download?.status_phase || '').toLowerCase()
  const key = STATUS_DETAIL_KEYS[phase]
  return key ? t(key) : ''
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
    loadDownloads()
  } catch (error) {
    logger.error('Failed to delete download:', error)
  } finally {
    deleting.value = false
  }
}

let pollTimer = null

onMounted(() => {
  loadDownloads()
  loadOverview()
  // Background refresh: the table, the live rate and the per-job progress bars
  // all update without a manual reload — silent, so no spinner flashes.
  pollTimer = setInterval(() => {
    loadDownloads(true)
    loadOverview()
  }, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.q-chip {
  font-weight: 500;
}

.download-status-detail {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
