<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminLists.title') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-4">
            <q-input
              v-model="filter"
              :label="$t('adminLists.search')"
              outlined
              dark
              dense
              clearable
              debounce="300"
            >
              <template v-slot:prepend><q-icon name="mdi-magnify" /></template>
            </q-input>
          </div>
          <div class="col-6 col-md-4">
            <q-select
              v-model="filterType"
              :options="typeOptions"
              :label="$t('adminLists.type')"
              dense
              outlined
              dark
              clearable
              emit-value
              map-options
              @update:model-value="onFilterChange"
            />
          </div>
          <div class="col-6 col-md-4">
            <q-select
              v-model="filterVisibility"
              :options="visibilityOptions"
              :label="$t('adminLists.visibility')"
              dense
              outlined
              dark
              clearable
              emit-value
              map-options
              @update:model-value="onFilterChange"
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
          @request="onRequest"
        >
          <template v-slot:body-cell-name="props">
            <q-td :props="props">
              <router-link
                :to="`/lists/${props.row.guid}`"
                class="text-primary cursor-pointer text-weight-medium"
                style="text-decoration: none"
              >
                {{ props.row.name }}
              </router-link>
            </q-td>
          </template>

          <template v-slot:body-cell-owner="props">
            <q-td :props="props">
              <router-link
                v-if="props.row.owner"
                :to="`/admin/users/${props.row.owner.guid}`"
                class="text-primary cursor-pointer"
                style="text-decoration: none"
              >
                {{ props.row.owner.first_name }} {{ props.row.owner.last_name }}
              </router-link>
              <q-badge v-else color="grey" :label="$t('adminLists.system')" />
            </q-td>
          </template>

          <template v-slot:body-cell-list_type="props">
            <q-td :props="props">
              <q-badge
                :color="props.value === 'system' ? 'orange' : 'primary'"
                :label="
                  props.value === 'system' ? $t('adminLists.systemType') : $t('adminLists.userType')
                "
              />
            </q-td>
          </template>

          <template v-slot:body-cell-visibility="props">
            <q-td :props="props">
              <q-icon
                :name="props.value === 'public' ? 'mdi-earth' : 'mdi-lock'"
                :color="props.value === 'public' ? 'positive' : 'warning'"
                size="sm"
              />
              <span class="q-ml-xs">
                {{ props.value === 'public' ? $t('adminLists.public') : $t('adminLists.private') }}
              </span>
            </q-td>
          </template>

          <template v-slot:body-cell-is_active="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-check-circle' : 'mdi-cancel'"
                :color="props.value ? 'positive' : 'negative'"
              />
            </q-td>
          </template>

          <template v-slot:body-cell-item_count="props">
            <q-td :props="props">
              <q-badge color="blue-grey" :label="props.value" />
            </q-td>
          </template>

          <template v-slot:body-cell-like_count="props">
            <q-td :props="props">
              <span v-if="props.value > 0">
                <q-icon name="mdi-heart" color="red" size="xs" />
                {{ props.value }}
              </span>
              <span v-else class="text-grey">0</span>
            </q-td>
          </template>

          <template v-slot:body-cell-created_at="props">
            <q-td :props="props">
              {{ formatDate(props.value) }}
            </q-td>
          </template>

          <template v-slot:body-cell-updated_at="props">
            <q-td :props="props">
              {{ formatDate(props.value) }}
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                size="sm"
                color="primary"
                round
                dense
                icon="mdi-eye"
                :to="`/lists/${props.row.guid}`"
                class="q-mr-xs"
              >
                <q-tooltip>{{ $t('adminLists.viewList') }}</q-tooltip>
              </q-btn>
              <q-btn
                size="sm"
                color="negative"
                round
                dense
                icon="mdi-delete"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ $t('adminLists.deleteList') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="deleteConfirmMessage"
      :loading="deleting"
      @confirm="deleteList"
    />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAdminLists, deleteAdminList } from 'src/services/contentAdminService'
import { useAdminCrudList } from 'src/composables/useAdminCrudList'
import { formatDate } from 'src/composables/useMediaFormatters'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()

const filterType = ref(null)
const filterVisibility = ref(null)

const {
  tableRef,
  rows,
  filter,
  loading,
  pagination,
  onRequest,
  refresh,
  showDeleteDialog,
  itemToDelete: listToDelete,
  deleting,
  confirmDelete,
  performDelete: deleteList,
} = useAdminCrudList({
  fetchPage: async ({ page, rowsPerPage, filter }) => {
    const params = { page, per_page: rowsPerPage }
    if (filter) params.search = filter
    if (filterType.value) params.list_type = filterType.value
    if (filterVisibility.value) params.visibility = filterVisibility.value
    const data = await getAdminLists(params)
    return { items: data.items, total: data.total }
  },
  deleteItem: (list) => deleteAdminList(list.guid),
  initialPagination: { sortBy: 'updated_at', rowsPerPage: 20 },
  errorContext: 'lists',
})

const deleteConfirmMessage = computed(() =>
  t('adminLists.deleteConfirm', { name: listToDelete.value?.name }),
)

const columns = [
  {
    name: 'name',
    label: t('adminLists.name'),
    align: 'left',
    field: 'name',
    sortable: true,
  },
  {
    name: 'owner',
    label: t('adminLists.owner'),
    align: 'left',
    field: (row) => row.owner?.first_name,
    sortable: false,
  },
  {
    name: 'list_type',
    label: t('adminLists.type'),
    align: 'center',
    field: 'list_type',
    sortable: true,
  },
  {
    name: 'visibility',
    label: t('adminLists.visibility'),
    align: 'center',
    field: 'visibility',
    sortable: true,
  },
  {
    name: 'item_count',
    label: t('adminLists.itemCount'),
    align: 'center',
    field: 'item_count',
    sortable: true,
  },
  {
    name: 'like_count',
    label: t('adminLists.likes'),
    align: 'center',
    field: 'like_count',
    sortable: true,
  },
  {
    name: 'is_active',
    label: t('adminLists.active'),
    align: 'center',
    field: 'is_active',
    sortable: true,
  },
  {
    name: 'created_at',
    label: t('adminLists.createdAt'),
    align: 'left',
    field: 'created_at',
    sortable: true,
  },
  {
    name: 'updated_at',
    label: t('adminLists.updatedAt'),
    align: 'left',
    field: 'updated_at',
    sortable: true,
  },
  {
    name: 'actions',
    label: t('adminLists.actions'),
    align: 'center',
    field: 'actions',
    sortable: false,
  },
]

const typeOptions = [
  { label: t('adminLists.systemType'), value: 'system' },
  { label: t('adminLists.userType'), value: 'user' },
]

const visibilityOptions = [
  { label: t('adminLists.public'), value: 'public' },
  { label: t('adminLists.private'), value: 'private' },
]

async function onFilterChange() {
  refresh()
}

onMounted(() => {
  refresh()
})
</script>
