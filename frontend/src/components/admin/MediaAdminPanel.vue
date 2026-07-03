<template>
  <MediaAdminFilesTable
    :files="files"
    :reprobing-files="reprobingFiles"
    :reprobing-file-id="reprobingFileId"
    :deleting-file-id="deletingFileId"
    class="q-mt-xl"
    @reprobe-all="$emit('reprobe-all')"
    @reprobe="$emit('reprobe', $event)"
    @delete-confirmed="$emit('delete-confirmed', $event)"
  />

  <MediaProviderRepairPanel
    :media-item="mediaItem"
    :is-song="isSong"
    @media-updated="$emit('media-updated')"
  />

  <MediaGameStreamingSettings
    v-if="isGame"
    :media-item="mediaItem"
    @media-updated="$emit('media-updated')"
  />

  <div class="q-mt-xl">
    <MediaMarkerEditor
      :media-id="mediaItem.guid"
      :media-type="mediaItem.media_type"
      :season-id="mediaItem.parent_guid"
      :duration="fileDuration"
    />
  </div>

  <MediaAdminReleasesTable
    :releases="releases"
    :searching="searchingReleases || isSearching"
    :downloading-release-id="downloadingReleaseId"
    @search="$emit('search')"
    @download="$emit('download', $event)"
    @delete-one="$emit('delete-one', $event)"
    @delete-all-confirmed="$emit('delete-all-confirmed')"
  />

  <MediaDownloadsTable :downloads="downloads" />
</template>

<script setup>
import MediaDownloadsTable from 'src/components/admin/MediaDownloadsTable.vue'
import MediaMarkerEditor from 'src/components/admin/MediaMarkerEditor.vue'
import MediaAdminFilesTable from 'src/components/admin/MediaFilesTable.vue'
import MediaAdminReleasesTable from 'src/components/admin/MediaReleasesTable.vue'
import MediaGameStreamingSettings from 'src/components/admin/MediaGameStreamingSettings.vue'
import MediaProviderRepairPanel from 'src/components/admin/MediaProviderRepairPanel.vue'

defineEmits([
  'reprobe-all',
  'reprobe',
  'delete-confirmed',
  'search',
  'download',
  'delete-one',
  'delete-all-confirmed',
  'media-updated',
])

defineProps({
  mediaItem: {
    type: Object,
    required: true,
  },
  files: {
    type: Array,
    default: () => [],
  },
  releases: {
    type: Array,
    default: () => [],
  },
  downloads: {
    type: Array,
    default: () => [],
  },
  fileDuration: {
    type: Number,
    default: 0,
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
  searchingReleases: Boolean,
  isSearching: Boolean,
  downloadingReleaseId: {
    type: [String, Number],
    default: null,
  },
  isSong: Boolean,
  isGame: Boolean,
})
</script>
