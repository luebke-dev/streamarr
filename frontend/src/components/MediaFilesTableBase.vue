<template>
  <div class="media-files-section q-mt-xl">
    <div class="section-header q-mb-md row items-center justify-between">
      <div>
        <h5 class="text-white q-my-none">{{ title }}</h5>
        <div v-if="countLabel" class="text-grey-4 text-caption">{{ countLabel }}</div>
      </div>
      <slot name="header-actions" />
    </div>

    <div v-if="rows.length === 0 && !loading && emptyTitle" class="empty-state q-pa-xl text-center">
      <q-icon :name="emptyIcon" size="4em" color="grey-5" class="q-mb-md" />
      <div class="text-h6 text-grey-4 q-mb-sm">{{ emptyTitle }}</div>
      <div v-if="emptyHint" class="text-grey-5">{{ emptyHint }}</div>
    </div>

    <div v-else-if="loading" class="q-pa-xl text-center">
      <q-spinner-dots size="3em" color="primary" />
      <div class="text-grey-4 q-mt-md">{{ loadingText }}</div>
    </div>

    <q-table
      v-else
      :rows="rows"
      :columns="columns"
      :row-key="rowKey"
      class="file-table bg-transparent"
      dark
      flat
      :bordered="bordered"
      :rows-per-page-options="rowsPerPageOptions"
      :pagination="pagination"
      :no-data-label="noDataLabel"
      binary-state-sort
    >
      <template #header="props">
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

      <template #body="props">
        <slot name="body" :props="props" />
      </template>

      <template #no-data="{ message }">
        <div class="full-width row flex-center text-grey-4 q-gutter-sm">
          <q-icon size="2em" name="mdi-folder-off" />
          <span>{{ message }}</span>
        </div>
      </template>
    </q-table>
  </div>
</template>

<script setup>
defineProps({
  rows: {
    type: Array,
    default: () => [],
  },
  columns: {
    type: Array,
    required: true,
  },
  title: {
    type: String,
    required: true,
  },
  countLabel: {
    type: String,
    default: '',
  },
  loading: Boolean,
  rowKey: {
    type: String,
    default: 'guid',
  },
  rowsPerPageOptions: {
    type: Array,
    default: () => [5, 10, 20],
  },
  pagination: {
    type: Object,
    default: () => ({ page: 1, rowsPerPage: 5 }),
  },
  noDataLabel: {
    type: String,
    default: '',
  },
  loadingText: {
    type: String,
    default: '',
  },
  emptyTitle: {
    type: String,
    default: '',
  },
  emptyHint: {
    type: String,
    default: '',
  },
  emptyIcon: {
    type: String,
    default: 'mdi-folder-open',
  },
  bordered: Boolean,
})
</script>

<style lang="scss" scoped>
@import 'src/css/dark-table';

.empty-state {
  @include dark-table-empty-state;
}

.file-table {
  @include dark-table-theme;
}
</style>
