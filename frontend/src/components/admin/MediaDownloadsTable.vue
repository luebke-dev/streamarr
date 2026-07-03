<template>
  <div class="releases-section q-mt-xl">
    <div class="section-header q-mb-md">
      <h5 class="text-white q-my-none">{{ $t('common.downloads') }} ({{ downloads.length }})</h5>
    </div>

    <q-table
      :rows="downloads"
      :columns="columns"
      row-key="guid"
      v-model:pagination="pagination"
      class="release-table bg-transparent"
      dark
      flat
      :rows-per-page-options="[5, 10, 25]"
      :no-data-label="$t('common.noDownloadsFound')"
      binary-state-sort
    >
      <template v-slot:header="props">
        <q-tr :props="props" class="table-header">
          <q-th
            v-for="col in props.cols"
            :key="col.name"
            :props="props"
            class="text-white bg-grey-9"
          >
            {{ col.label }}
          </q-th>
        </q-tr>
      </template>

      <template v-slot:body="props">
        <q-tr :props="props" class="table-row">
          <q-td key="title" :props="props" class="release-title-cell">
            <div class="release-title text-white">{{ props.row.title }}</div>
          </q-td>

          <q-td key="status" :props="props" class="text-center">
            <template v-if="props.row.status">
              <q-chip
                :label="
                  $t(
                    `adminDownloads.statuses.${(props.row.status || '').toLowerCase()}`,
                    props.row.status,
                  )
                "
                :color="statusColor(props.row.status)"
                text-color="white"
                size="sm"
              >
                <q-tooltip v-if="props.row.error_reason" class="text-body2" max-width="400px">
                  {{ props.row.error_reason }}
                </q-tooltip>
              </q-chip>
              <div
                v-if="statusDetail(props.row)"
                class="download-status-detail text-grey-5 text-caption q-mt-xs"
              >
                {{ statusDetail(props.row) }}
              </div>
            </template>
            <span v-else class="text-grey-5">-</span>
          </q-td>

          <q-td key="progress" :props="props" class="text-center">
            <div
              v-if="props.row.progress != null && props.row.status === 'downloading'"
              class="row items-center q-gutter-xs"
            >
              <q-linear-progress
                :value="props.row.progress / 100"
                color="primary"
                track-color="grey-8"
                rounded
                style="width: 80px"
              />
              <span class="text-grey-4 text-caption">{{ Math.round(props.row.progress) }}%</span>
            </div>
            <span v-else class="text-grey-5">-</span>
          </q-td>

          <q-td key="created_at" :props="props" class="text-center">
            <span class="text-grey-5">{{ formatDate(props.row.created_at) }}</span>
          </q-td>
        </q-tr>
      </template>
    </q-table>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

defineProps({
  downloads: { type: Array, default: () => [] },
})

const { t } = useI18n()

const columns = ref([
  {
    name: 'title',
    required: true,
    label: t('common.title'),
    align: 'left',
    field: 'title',
    sortable: true,
    style: 'width: 50%',
  },
  {
    name: 'status',
    align: 'center',
    label: t('common.status'),
    field: 'status',
    sortable: true,
    style: 'width: 15%',
  },
  {
    name: 'progress',
    align: 'center',
    label: t('common.progress'),
    field: 'progress',
    sortable: true,
    style: 'width: 25%',
  },
  {
    name: 'created_at',
    align: 'center',
    label: t('common.added'),
    field: 'created_at',
    sortable: true,
    style: 'width: 10%',
  },
  {
    name: 'started_by_name',
    align: 'center',
    label: t('common.startedBy'),
    field: 'started_by_name',
    sortable: false,
    style: 'width: 15%',
    format: (val) => val || '-',
  },
])

const pagination = ref({
  sortBy: 'created_at',
  descending: true,
  page: 1,
  rowsPerPage: 5,
})

const STATUS_COLORS = {
  queued: 'grey',
  pending: 'grey',
  downloading: 'blue',
  paused: 'orange',
  completed: 'positive',
  failed: 'negative',
  imported: 'teal',
}
const statusColor = (status) => STATUS_COLORS[(status || '').toLowerCase()] || 'grey'

const STATUS_DETAIL_KEYS = {
  preparing: 'adminDownloads.statusDetails.preparing',
  searching: 'adminDownloads.statusDetails.searching',
  retrying_release: 'adminDownloads.statusDetails.retryingRelease',
  importing: 'adminDownloads.statusDetails.importing',
}

const statusDetail = (download) => {
  const explicitDetail = download?.status_detail || download?.error_reason
  if (explicitDetail) return explicitDetail

  const phase = (download?.status_phase || '').toLowerCase()
  const key = STATUS_DETAIL_KEYS[phase]
  return key ? t(key) : ''
}

// Locale-specific date formatter (de-DE, dash fallback) — matches the
// formatDate variant the page used before extraction.
const formatDate = (dateString) => {
  if (!dateString) return '-'
  return new Intl.DateTimeFormat('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date(dateString))
}
</script>

<style scoped>
.download-status-detail {
  margin-inline: auto;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
