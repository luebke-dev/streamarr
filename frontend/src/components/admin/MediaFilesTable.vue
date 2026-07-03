<template>
  <MediaFilesTableBase
    :rows="files"
    :columns="fileColumns"
    :title="$t('common.files')"
    :count-label="`(${files.length})`"
    :pagination="filePagination"
    :no-data-label="$t('common.noFilesAvailable')"
  >
    <template #header-actions>
      <q-btn
        flat
        dense
        color="primary"
        icon="mdi-refresh"
        :label="$t('common.reprobeAll')"
        :loading="reprobingFiles"
        @click="$emit('reprobe-all')"
      />
    </template>

    <template #body="{ props }">
      <q-tr :props="props" class="table-row">
        <q-td key="file_name" :props="props" class="file-name-cell">
          <div class="file-name-content">
            <q-icon name="mdi-file-video" color="primary" size="sm" class="q-mr-sm" />
            <span class="file-name text-white">
              {{ props.row.file_name || getFileName(props.row.file_path) }}
            </span>
          </div>
        </q-td>

        <q-td key="resolution" :props="props" class="text-center">
          <q-chip
            v-if="props.row.width && props.row.height"
            :label="`${props.row.width}x${props.row.height}`"
            color="primary"
            text-color="white"
            size="sm"
            icon="mdi-aspect-ratio"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="codec" :props="props" class="text-center">
          <q-chip
            v-if="props.row.codec"
            :label="props.row.codec"
            color="accent"
            text-color="white"
            size="sm"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="quality" :props="props" class="text-center">
          <q-chip
            v-if="props.row.quality"
            :label="props.row.quality"
            color="warning"
            text-color="white"
            size="sm"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="file_size" :props="props" class="text-center">
          <div v-if="props.row.file_size" class="size-container">
            <q-icon name="mdi-database" color="positive" size="sm" class="q-mr-xs" />
            <span>{{ formatFileSize(props.row.file_size) }}</span>
          </div>
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="duration" :props="props" class="text-center">
          <span v-if="props.row.duration">
            {{ formatDuration(props.row.duration) }}
          </span>
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="actions" :props="props" class="text-center">
          <q-btn
            flat
            round
            dense
            icon="mdi-refresh"
            color="primary"
            size="sm"
            :loading="reprobingFileId === props.row.guid"
            @click="$emit('reprobe', props.row)"
          >
            <q-tooltip>{{ $t('common.reprobe') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat
            round
            dense
            icon="mdi-delete"
            color="negative"
            size="sm"
            :loading="deletingFileId === props.row.guid"
            @click="confirmDelete(props.row)"
          >
            <q-tooltip>{{ $t('common.deleteFile') }}</q-tooltip>
          </q-btn>
        </q-td>
      </q-tr>
    </template>
  </MediaFilesTableBase>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import MediaFilesTableBase from 'src/components/MediaFilesTableBase.vue'
import { formatFileSize, formatDuration, getFileName } from 'src/composables/useMediaFormatters'

defineProps({
  files: {
    type: Array,
    required: true,
  },
  reprobingFiles: Boolean,
  reprobingFileId: {
    type: [String, Number],
    default: null,
  },
  deletingFileId: {
    type: [String, Number],
    default: null,
  },
})

const emit = defineEmits(['reprobe-all', 'reprobe', 'delete-confirmed'])
const { t } = useI18n()
const $q = useQuasar()

const fileColumns = computed(() => [
  {
    name: 'file_name',
    required: true,
    label: t('common.fileName'),
    align: 'left',
    field: (row) => row.file_name || row.file_path,
    sortable: true,
    style: 'width: 40%',
  },
  {
    name: 'resolution',
    align: 'center',
    label: t('common.resolution'),
    field: (row) => (row.width && row.height ? `${row.width}x${row.height}` : null),
    sortable: true,
    style: 'width: 12%',
  },
  {
    name: 'codec',
    align: 'center',
    label: t('common.codec'),
    field: 'codec',
    sortable: true,
    style: 'width: 12%',
  },
  {
    name: 'quality',
    align: 'center',
    label: t('common.quality'),
    field: 'quality',
    sortable: true,
    style: 'width: 12%',
  },
  {
    name: 'file_size',
    align: 'center',
    label: t('common.size'),
    field: 'file_size',
    sortable: true,
    sort: (a, b) => (a || 0) - (b || 0),
    style: 'width: 12%',
  },
  {
    name: 'duration',
    align: 'center',
    label: t('common.duration'),
    field: 'duration',
    sortable: true,
    style: 'width: 10%',
  },
  {
    name: 'actions',
    align: 'center',
    label: t('common.actions'),
    field: 'guid',
    sortable: false,
    style: 'width: 8%',
  },
])

const filePagination = ref({
  sortBy: 'file_name',
  descending: false,
  page: 1,
  rowsPerPage: 5,
})

function confirmDelete(file) {
  $q.dialog({
    title: t('common.deleteFile'),
    message: t('common.deleteFileConfirm', {
      name: file.file_name || getFileName(file.file_path) || file.guid,
    }),
    ok: { label: t('common.delete'), color: 'negative', flat: true },
    cancel: { label: t('common.cancel'), color: 'grey-7', flat: true },
    dark: true,
  }).onOk(() => {
    emit('delete-confirmed', file)
  })
}
</script>

<style scoped>
.file-name-content,
.size-container {
  display: inline-flex;
  align-items: center;
}
</style>
