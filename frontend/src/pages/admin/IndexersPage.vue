<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminIndexers.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminIndexers.subtitle') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model="filter"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
              debounce="300"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>

          <div class="col-12 col-md-6 text-right">
            <q-btn
              color="primary"
              icon="mdi-plus"
              :label="$t('adminIndexers.addIndexer')"
              @click="$router.push('/admin/indexers/create')"
              unelevated
            />
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          ref="tableRef"
          :rows="rows"
          :columns="columns"
          row-key="guid"
          v-model:pagination="pagination"
          :loading="loading"
          :filter="filter"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
          @request="onRequest"
        >
          <template v-slot:body-cell-type="props">
            <q-td :props="props">
              <q-chip :label="props.value" size="sm" color="primary" text-color="white" />
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                flat
                dense
                round
                icon="mdi-pencil"
                color="primary"
                size="sm"
                @click="$router.push(`/admin/indexers/${props.row.guid}/edit`)"
              >
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
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

    <!-- Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminIndexers.deleteConfirm')"
      :loading="deleting"
      @confirm="deleteIndexer"
    />
  </q-page>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { useAdminCrudList } from 'src/composables/useAdminCrudList'
import { useCachedClientPagination } from 'src/composables/useCachedClientPagination'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()

const { paginate: paginateIndexers, invalidate: invalidateIndexersCache } =
  useCachedClientPagination({
    loadAll: async () => {
      const response = await api.get('/api/indexers')
      return response.data
    },
    matchFilter: (row, needle) =>
      (row.label && row.label.toLowerCase().includes(needle)) ||
      (row.type && row.type.toLowerCase().includes(needle)) ||
      (row.host && row.host.toLowerCase().includes(needle)),
  })

const {
  tableRef,
  rows,
  filter,
  loading,
  pagination,
  onRequest,
  refresh,
  showDeleteDialog,
  deleting,
  confirmDelete,
  performDelete: deleteIndexer,
} = useAdminCrudList({
  fetchPage: paginateIndexers,
  deleteItem: async (indexer) => {
    await api.delete(`/api/indexers/${indexer.guid}`)
    invalidateIndexersCache()
  },
  errorContext: 'indexers',
})

const columns = computed(() => [
  {
    name: 'label',
    required: true,
    label: t('adminIndexers.fields.label'),
    align: 'left',
    field: 'label',
    sortable: true,
  },
  {
    name: 'type',
    align: 'left',
    label: t('adminIndexers.fields.type'),
    field: 'type',
    sortable: true,
  },
  {
    name: 'host',
    align: 'left',
    label: t('common.host'),
    field: 'host',
    sortable: true,
  },
  {
    name: 'created_at',
    align: 'left',
    label: t('adminIndexers.fields.createdAt'),
    field: 'created_at',
    format: (val) => new Date(val).toLocaleDateString(),
    sortable: true,
  },
  {
    name: 'actions',
    align: 'center',
    label: t('common.actions'),
    field: 'actions',
  },
])

onMounted(() => {
  refresh()
})
</script>
