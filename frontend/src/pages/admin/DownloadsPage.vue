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

    <!-- Summary -->
    <div class="row q-col-gutter-md q-mb-md">
      <div v-for="card in summaryCards" :key="card.key" class="col-6 col-md-3">
        <q-card class="admin-stat" flat>
          <q-card-section class="row items-center no-wrap q-pa-sm">
            <q-avatar :color="card.color" text-color="white" size="42px" class="q-mr-md">
              <q-icon :name="card.icon" size="20px" />
            </q-avatar>
            <div class="col">
              <div class="admin-stat-label">{{ card.label }}</div>
              <div class="admin-stat-value">{{ card.value }}</div>
              <div class="admin-stat-sub ellipsis">{{ card.sub }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Queue control -->
    <q-card class="admin-card q-mb-md" flat>
      <q-card-section class="q-py-sm row items-center justify-between">
        <div class="admin-heading">{{ $t('adminDownloads.control') }}</div>
        <div class="row items-center q-gutter-xs">
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
        </div>
      </q-card-section>

      <q-separator />

      <q-card-section class="row items-center q-col-gutter-md q-py-md">
        <div class="col-auto">
          <q-btn
            unelevated
            no-caps
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

        <div class="col-auto">
          <div class="row items-center no-wrap">
            <q-input
              v-model.number="speedLimitKbps"
              :label="$t('adminDownloads.queue.speedLimit')"
              type="number"
              min="0"
              outlined
              dark
              dense
              style="width: 150px"
              :hint="$t('adminDownloads.queue.speedLimitHint')"
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
        </div>

        <q-space />

        <div class="col-auto">
          <q-chip
            :color="queuePaused ? 'warning' : 'positive'"
            text-color="white"
            dense
            :icon="queuePaused ? 'mdi-pause-circle' : 'mdi-download-network'"
            :label="queuePaused ? $t('adminDownloads.queue.paused') : $t('adminDownloads.queue.running')"
          />
        </div>
      </q-card-section>

      <template v-if="activeJobs.length">
        <q-separator />
        <q-card-section class="q-py-md column q-gutter-md">
          <div v-for="job in activeJobs" :key="job.id">
            <div class="row items-baseline justify-between q-mb-xs">
              <div class="col ellipsis text-body2">{{ job.name }}</div>
              <div class="col-auto text-caption text-grey-5 q-ml-md">
                {{ Math.round(job.progress) }}% &middot; {{ formatSpeed(job.speed_bps) }}
                <template v-if="job.total_bytes">
                  &middot; {{ formatBytes(job.downloaded_bytes) }} /
                  {{ formatBytes(job.total_bytes) }}
                </template>
              </div>
            </div>
            <q-linear-progress
              :value="job.progress / 100"
              color="info"
              track-color="grey-9"
              rounded
              size="6px"
              class="q-mb-xs"
            />
          </div>
        </q-card-section>
      </template>
    </q-card>

    <!-- Downloads -->
    <q-card class="admin-card" flat>
      <q-card-section class="row items-center q-col-gutter-md q-py-sm">
        <div class="col">
          <div class="admin-heading">
            {{ $t('adminDownloads.history') }}
            <span class="text-grey-6">({{ downloads.length }})</span>
          </div>
        </div>
        <div class="col-12 col-md-3">
          <q-input
            v-model="search"
            :placeholder="$t('common.search')"
            outlined
            dark
            dense
            clearable
            @update:model-value="debouncedSearch"
          >
            <template v-slot:prepend>
              <q-icon name="mdi-magnify" size="xs" />
            </template>
          </q-input>
        </div>
        <div class="col-12 col-md-2">
          <q-select
            v-model="statusFilter"
            :options="statusOptions"
            :placeholder="$t('adminDownloads.filterByStatus')"
            outlined
            dark
            dense
            emit-value
            map-options
            clearable
            @update:model-value="loadDownloads"
          />
        </div>
      </q-card-section>

      <q-separator />

      <q-table
        flat
        dark
        class="admin-table"
        :rows="downloads"
        :columns="columns"
        :loading="loading"
        row-key="guid"
        binary-state-sort
        :rows-per-page-options="[25, 50, 100, 0]"
        :pagination="{ rowsPerPage: 25 }"
      >
        <template v-slot:body-cell-type="props">
          <q-td :props="props">
            <q-icon :name="getTypeIcon(props.value)" size="18px" :color="getTypeColor(props.value)">
              <q-tooltip>{{ getTypeLabel(props.value) }}</q-tooltip>
            </q-icon>
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
            <div class="row-meta">
              <span v-if="props.row.show_title && props.row.season_number != null">
                S{{ String(props.row.season_number).padStart(2, '0') }}E{{
                  String(props.row.episode_number ?? 0).padStart(2, '0')
                }}
                &middot;
              </span>
              <span v-if="props.row.started_by_name">{{ props.row.started_by_name }}</span>
              <span v-if="props.row.started_by_name && props.row.created_at"> &middot; </span>
              <span v-if="props.row.created_at">{{
                formatRelativeTime(props.row.created_at)
              }}</span>
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-status="props">
          <q-td :props="props">
            <q-badge
              :color="getStatusColor(props.value)"
              :label="getStatusLabel(props.value)"
              class="status-badge"
            />
            <div v-if="getStatusDetail(props.row)" class="row-meta ellipsis">
              {{ getStatusDetail(props.row) }}
            </div>
          </q-td>
        </template>

        <template v-slot:body-cell-progress="props">
          <q-td :props="props">
            <div v-if="props.value !== null" class="row items-center no-wrap">
              <q-linear-progress
                :value="props.value / 100"
                :color="props.value >= 100 ? 'positive' : 'info'"
                track-color="grey-9"
                class="col q-mr-sm"
                size="5px"
                rounded
              />
              <span class="text-caption text-grey-5">{{ Math.round(props.value) }}%</span>
            </div>
            <span v-else class="text-grey-7">–</span>
          </q-td>
        </template>

        <template v-slot:body-cell-speed_bps="props">
          <q-td :props="props">
            <span :class="props.value > 0 ? 'text-grey-4' : 'text-grey-7'">
              {{ formatSpeed(props.value) }}
            </span>
          </q-td>
        </template>

        <template v-slot:body-cell-downloader_name="props">
          <q-td :props="props">
            <q-icon
              v-if="props.value"
              :name="props.row.downloader_type === 'sabnzbd' ? 'mdi-server' : 'mdi-download'"
              size="16px"
              class="text-grey-6"
            >
              <q-tooltip>{{ props.value }}</q-tooltip>
            </q-icon>
            <span v-else class="text-grey-7">–</span>
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
          </q-td>
        </template>

        <template v-slot:no-data>
          <div class="column items-center q-pa-xl text-center">
            <q-icon name="mdi-tray-remove" size="40px" class="text-grey-8 q-mb-sm" />
            <div class="text-grey-5">{{ $t('adminDownloads.emptyTitle') }}</div>
            <div class="text-caption text-grey-7">
              {{ $t('adminDownloads.emptyHint') }}
            </div>
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
import { debounce } from 'quasar'
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
const activeJobs = computed(() => overview.value?.jobs || [])

// The four cards at the top answer "is anything happening, how fast, and is the
// queue blocked" before the table is read. Driven by one table so the cards stay
// identical in shape.
const summaryCards = computed(() => {
  const counts = overview.value?.counts || {}
  const clients = downloaders.value
  const reachable = clients.filter((c) => c.reachable).length
  return [
    {
      key: 'rate',
      icon: 'mdi-speedometer',
      color: queuePaused.value ? 'grey-8' : 'info',
      label: t('adminDownloads.summary.rate'),
      value: formatSpeed(overview.value?.speed_bps),
      sub: queuePaused.value
        ? t('adminDownloads.queue.paused')
        : t('adminDownloads.summary.live'),
    },
    {
      key: 'active',
      icon: 'mdi-tray-full',
      color: 'teal',
      label: t('adminDownloads.summary.active'),
      value: counts.downloading ?? 0,
      sub: t('adminDownloads.summary.jobs', { n: activeJobs.value.length }),
    },
    {
      key: 'queued',
      icon: 'mdi-timer-sand',
      color: 'purple',
      label: t('adminDownloads.summary.queued'),
      value: counts.queued ?? 0,
      sub: t('adminDownloads.summary.waiting'),
    },
    {
      key: 'clients',
      icon: 'mdi-server-network',
      color: reachable === clients.length && clients.length ? 'green' : 'orange',
      label: t('adminDownloads.summary.clients'),
      value: `${reachable}/${clients.length}`,
      sub: t('adminDownloads.summary.reachable'),
    },
  ]
})

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

const statusOptions = computed(() => [
  { label: t('adminDownloads.statuses.pending'), value: 'pending' },
  { label: t('adminDownloads.statuses.queued'), value: 'queued' },
  { label: t('adminDownloads.statuses.downloading'), value: 'downloading' },
  { label: t('adminDownloads.statuses.paused'), value: 'paused' },
  { label: t('adminDownloads.statuses.completed'), value: 'completed' },
  { label: t('adminDownloads.statuses.failed'), value: 'failed' },
  { label: t('adminDownloads.statuses.imported'), value: 'imported' },
])

// Six columns instead of nine: show/episode, user and time live as a caption
// under the title, and the downloader shrinks to an icon with a tooltip.
const columns = computed(() => [
  {
    name: 'type',
    label: '',
    align: 'center',
    field: 'type',
    sortable: false,
    style: 'width: 36px',
    headerStyle: 'width: 36px',
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
    style: 'width: 170px',
  },
  {
    name: 'progress',
    label: t('adminDownloads.columns.progress'),
    align: 'left',
    field: 'progress',
    sortable: true,
    style: 'width: 150px',
  },
  {
    name: 'speed_bps',
    label: t('adminDownloads.columns.speed'),
    align: 'right',
    field: 'speed_bps',
    sortable: true,
    style: 'width: 100px',
  },
  {
    name: 'downloader_name',
    label: t('adminDownloads.columns.downloader'),
    align: 'center',
    field: 'downloader_name',
    style: 'width: 60px',
    headerStyle: 'width: 60px',
  },
  {
    name: 'actions',
    label: '',
    align: 'right',
    field: 'actions',
    style: 'width: 110px',
  },
])

const loadDownloads = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    let rows = (await listDownloads()) || []

    if (search.value) {
      const needle = search.value.toLowerCase()
      rows = rows.filter((d) => (d.display_title || '').toLowerCase().includes(needle))
    }

    if (statusFilter.value) {
      rows = rows.filter((d) => (d.status || '').toLowerCase() === statusFilter.value)
    }

    downloads.value = rows
  } catch (error) {
    logger.error('Failed to load downloads:', error)
  } finally {
    if (!silent) loading.value = false
  }
}

const refreshAll = () => Promise.all([loadDownloads(), loadOverview()])

const debouncedSearch = debounce(() => {
  loadDownloads()
}, 500)

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

const getTypeLabel = (type) => {
  const t = (type || '').toLowerCase()
  return t(`adminDownloads.types.${t}`, type || '')
}

const getStatusColor = (status) => {
  const s = (status || '').toLowerCase()
  const colors = {
    queued: 'grey',
    downloading: 'info',
    paused: 'warning',
    completed: 'positive',
    failed: 'negative',
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

const POLL_MS = 5000
let pollTimer = null

onMounted(() => {
  refreshAll()
  // Background refresh: the table, the live rate and the per-job progress bars
  // all update without a manual reload — silent, so no spinner flashes.
  pollTimer = setInterval(() => {
    loadDownloads(true)
    loadOverview()
  }, POLL_MS)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
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
  font-size: 0.72rem;
  color: #8b8b8b;
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-badge {
  font-weight: 500;
  padding: 2px 8px;
}
</style>
