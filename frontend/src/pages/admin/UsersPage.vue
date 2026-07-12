<template>
  <q-page class="q-pa-md">
    <div class="row items-center justify-between q-mb-md">
      <div class="text-h4">{{ $t('adminUsers.title') }}</div>
      <q-btn
        color="primary"
        icon="mdi-plus"
        :label="$t('adminUsers.addUser')"
        no-caps
        @click="$router.push('/admin/users/create')"
      />
    </div>

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
              <template v-slot:prepend><q-icon name="mdi-magnify" /></template>
            </q-input>
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
          <template v-slot:body-cell-first_name="props">
            <q-td :props="props">
              <router-link
                :to="`/admin/users/${props.row.guid}`"
                class="text-primary cursor-pointer text-weight-medium"
                style="text-decoration: none"
              >
                {{ props.row.first_name }}
              </router-link>
            </q-td>
          </template>

          <template v-slot:body-cell-last_name="props">
            <q-td :props="props">
              <router-link
                :to="`/admin/users/${props.row.guid}`"
                class="text-primary cursor-pointer text-weight-medium"
                style="text-decoration: none"
              >
                {{ props.row.last_name }}
              </router-link>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                size="sm"
                color="primary"
                round
                dense
                icon="mdi-pencil"
                @click="$router.push(`/admin/users/${props.row.guid}/edit`)"
                class="q-mr-xs"
              />
              <q-btn
                size="sm"
                color="negative"
                round
                dense
                icon="mdi-delete"
                @click="confirmDelete(props.row)"
              />
              <q-btn
                size="sm"
                color="primary"
                round
                dense
                icon="mdi-format-list-bulleted"
                @click="viewUserLists(props.row)"
                class="q-ml-xs"
              />
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

          <template v-slot:body-cell-is_superuser="props">
            <q-td :props="props">
              <q-icon
                :name="props.value ? 'mdi-shield-account' : 'mdi-account'"
                :color="props.value ? 'orange' : 'grey'"
              />
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- User Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminUsers.deleteConfirm')"
      :loading="deleting"
      @confirm="deleteUser"
    />
  </q-page>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { useRouter } from 'vue-router'
import { useAdminCrudList } from 'src/composables/useAdminCrudList'
import { useCachedClientPagination } from 'src/composables/useCachedClientPagination'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()
const router = useRouter()

const { paginate: paginateUsers, invalidate: invalidateUsersCache } = useCachedClientPagination({
  loadAll: async () => {
    const response = await api.get('/api/users')
    return response.data
  },
  matchFilter: (row, needle) =>
    (row.first_name && row.first_name.toLowerCase().includes(needle)) ||
    (row.last_name && row.last_name.toLowerCase().includes(needle)) ||
    (row.email && row.email.toLowerCase().includes(needle)),
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
  performDelete: deleteUser,
} = useAdminCrudList({
  fetchPage: paginateUsers,
  deleteItem: async (user) => {
    await api.delete(`/api/users/${user.guid}`)
    invalidateUsersCache()
  },
  errorContext: 'users',
})

const columns = computed(() => [
  {
    name: 'first_name',
    required: true,
    label: t('adminUsers.colFirstName'),
    align: 'left',
    field: 'first_name',
    format: (val) => `${val}`,
    sortable: true,
  },
  {
    name: 'last_name',
    align: 'left',
    label: t('adminUsers.colLastName'),
    field: 'last_name',
    sortable: true,
  },
  {
    name: 'email',
    align: 'left',
    label: t('adminUsers.colEmail'),
    field: 'email',
    sortable: true,
  },
  {
    name: 'is_active',
    align: 'center',
    label: t('adminUsers.colActive'),
    field: 'is_active',
    sortable: true,
  },
  {
    name: 'is_superuser',
    align: 'center',
    label: t('adminUsers.colRole'),
    field: 'is_superuser',
    sortable: true,
  },
  {
    name: 'created_at',
    align: 'left',
    label: t('adminUsers.colCreated'),
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

function viewUserLists(user) {
  router.push(`/admin/users/${user.guid}`)
}

onMounted(() => {
  refresh()
})
</script>
