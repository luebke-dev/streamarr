<template>
  <MediaReleasesTableBase
    :rows="releases"
    :columns="releaseColumns"
    :title="$t('common.releases')"
    :count-label="`(${releases.length})`"
    :pagination="releasePagination"
    :no-data-label="$t('common.noReleasesFound')"
  >
    <template #header-actions>
      <div class="q-gutter-sm">
        <q-btn
          flat
          dense
          icon="mdi-magnify"
          color="primary"
          :label="$t('common.searchReleases')"
          size="sm"
          :loading="searching"
          :disable="searching"
          @click="$emit('search')"
        />
        <q-btn
          v-if="releases.length > 0"
          flat
          dense
          icon="mdi-delete-sweep"
          color="red-5"
          :label="$t('common.deleteAll')"
          size="sm"
          @click="confirmDeleteAll"
        />
      </div>
    </template>

    <template #body="{ props }">
      <q-tr
        :props="props"
        class="table-row"
        :class="{ 'blacklisted-row': props.row.blacklisted_reason }"
      >
        <q-td key="title" :props="props" class="release-title-cell">
          <div class="release-title" :class="props.row.blacklisted_reason ? 'text-grey-6' : 'text-white'">
            {{ props.row.title }}
            <q-badge v-if="props.row.blacklisted_reason" color="red" class="q-ml-sm">
              <q-icon name="mdi-cancel" size="xs" class="q-mr-xs" />
              {{ $t('common.blacklisted', 'Blacklisted') }}
              <q-tooltip>{{ props.row.blacklisted_reason }}</q-tooltip>
            </q-badge>
          </div>
        </q-td>

        <q-td key="score" :props="props" class="text-center">
          <q-chip
            v-if="props.row.score != null"
            :label="props.row.score.toString()"
            :color="getScoreColor(props.row.score)"
            text-color="white"
            size="sm"
            icon="mdi-star"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="resolution" :props="props" class="text-center">
          <q-chip
            v-if="props.row.release_metadata?.resolution"
            :label="props.row.release_metadata.resolution"
            color="teal"
            text-color="white"
            size="sm"
            icon="mdi-aspect-ratio"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="codec" :props="props" class="text-center">
          <q-chip
            v-if="props.row.release_metadata?.video_codec"
            :label="props.row.release_metadata.video_codec"
            color="accent"
            text-color="white"
            size="sm"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="source" :props="props" class="text-center">
          <q-chip
            v-if="props.row.release_metadata?.source"
            :label="getSourceLabel(props.row.release_metadata.source)"
            :color="getSourceColor(props.row.release_metadata.source)"
            text-color="white"
            size="sm"
            icon="mdi-download-network"
          />
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="languages" :props="props" class="text-center">
          <div v-if="props.row.release_metadata?.languages?.length" class="language-flags">
            <span
              v-for="lang in props.row.release_metadata.languages"
              :key="lang"
              class="lang-flag"
            >
              {{ langToFlag(lang) }}
              <q-tooltip>{{ langToName(lang) }}</q-tooltip>
            </span>
          </div>
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="size" :props="props" class="text-center">
          <div v-if="props.row.size" class="size-container">
            <q-icon name="mdi-database" color="positive" size="sm" class="q-mr-xs" />
            <span>{{ formatFileSize(props.row.size) }}</span>
          </div>
          <span v-else class="text-grey-5">-</span>
        </q-td>

        <q-td key="links" :props="props" class="text-center">
          <div class="links-container">
            <q-icon name="mdi-link" color="grey" size="sm" class="q-mr-xs" />
            <span>{{ props.row.links?.length || 0 }}</span>
          </div>
        </q-td>

        <q-td key="download_action" :props="props" class="text-center">
          <div class="row no-wrap justify-center q-gutter-xs">
            <q-btn
              flat
              round
              dense
              icon="mdi-download"
              :color="props.row.links?.length ? 'primary' : 'grey-6'"
              :disable="!props.row.links?.length"
              size="sm"
              :loading="downloadingReleaseId === props.row.guid"
              @click="$emit('download', props.row)"
            >
              <q-tooltip v-if="props.row.links?.length">
                {{ $t('common.startDownload') }}
              </q-tooltip>
              <q-tooltip v-else>{{ $t('common.releaseHasNoLinks') }}</q-tooltip>
            </q-btn>
            <q-btn
              flat
              round
              dense
              icon="mdi-delete"
              color="red-5"
              size="sm"
              @click="$emit('delete-one', props.row)"
            >
              <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
            </q-btn>
          </div>
        </q-td>
      </q-tr>
    </template>
  </MediaReleasesTableBase>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import MediaReleasesTableBase from 'src/components/MediaReleasesTableBase.vue'
import { formatFileSize } from 'src/composables/useMediaFormatters'
import {
  getScoreColor,
  getSourceColor,
  getSourceLabel,
  langToFlag,
  langToName,
} from 'src/composables/useReleaseFormatters'

const props = defineProps({
  releases: {
    type: Array,
    required: true,
  },
  searching: Boolean,
  downloadingReleaseId: {
    type: [String, Number],
    default: null,
  },
})

const emit = defineEmits(['search', 'download', 'delete-one', 'delete-all-confirmed'])
const { t } = useI18n()
const $q = useQuasar()

const releaseColumns = computed(() => [
  {
    name: 'title',
    required: true,
    label: t('common.title'),
    align: 'left',
    field: 'title',
    sortable: true,
    style: 'width: 30%',
  },
  {
    name: 'score',
    align: 'center',
    label: t('common.score'),
    field: 'score',
    sortable: true,
    sort: (a, b) => (a || 0) - (b || 0),
    style: 'width: 8%',
  },
  {
    name: 'resolution',
    align: 'center',
    label: t('common.resolution'),
    field: (row) => row.release_metadata?.resolution || null,
    sortable: true,
    style: 'width: 10%',
  },
  {
    name: 'codec',
    align: 'center',
    label: t('common.codec'),
    field: (row) => row.release_metadata?.video_codec || null,
    sortable: true,
    style: 'width: 10%',
  },
  {
    name: 'source',
    align: 'center',
    label: t('common.source'),
    field: (row) => row.release_metadata?.source || null,
    sortable: true,
    style: 'width: 10%',
  },
  {
    name: 'languages',
    align: 'center',
    label: t('common.languages'),
    field: (row) => row.release_metadata?.languages?.join(', ') || null,
    sortable: true,
    style: 'width: 8%',
  },
  {
    name: 'size',
    align: 'center',
    label: t('common.size'),
    field: 'size',
    sortable: true,
    sort: (a, b) => (a || 0) - (b || 0),
    style: 'width: 10%',
  },
  {
    name: 'links',
    align: 'center',
    label: t('common.links'),
    field: (row) => row.links?.length || 0,
    sortable: true,
    sort: (a, b) => (b || 0) - (a || 0),
    style: 'width: 8%',
  },
  {
    name: 'download_action',
    align: 'center',
    label: '',
    field: 'guid',
    sortable: false,
    style: 'width: 5%',
  },
])

const releasePagination = ref({
  sortBy: 'score',
  descending: true,
  page: 1,
  rowsPerPage: 5,
})

function confirmDeleteAll() {
  $q.dialog({
    title: t('common.confirmDeleteAll'),
    message: t('common.confirmDeleteAllReleases', { count: props.releases.length }),
    cancel: true,
    persistent: true,
  }).onOk(() => {
    emit('delete-all-confirmed')
  })
}
</script>

<style scoped>
.release-title {
  font-weight: 500;
  word-break: break-word;
}

.blacklisted-row {
  opacity: 0.55;
}

.language-flags {
  display: inline-flex;
  gap: 4px;
}

.lang-flag {
  font-size: 1.1em;
}

.size-container,
.links-container {
  display: inline-flex;
  align-items: center;
}
</style>
