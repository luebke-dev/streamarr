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

    <!-- List Create/Edit Dialog -->
    <q-dialog v-model="showCreateListDialog" persistent>
      <q-card dark style="min-width: 500px">
        <q-card-section>
          <div class="text-h6">
            {{ listEditMode ? $t('adminUsers.editList') : $t('adminUsers.createList') }}
          </div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="saveList" class="q-gutter-md">
            <q-input
              outlined
              dark
              dense
              v-model="listForm.name"
              :label="$t('adminUsers.listName')"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || $t('adminUsers.listNameRequired')]"
            />

            <q-input
              outlined
              dark
              dense
              v-model="listForm.description"
              :label="$t('adminUsers.description')"
              type="textarea"
              rows="3"
            />

            <q-select
              outlined
              dark
              dense
              v-model="listForm.list_type"
              :options="listTypes"
              :label="$t('adminUsers.type')"
              lazy-rules
              :rules="[(val) => val || $t('adminUsers.typeRequired')]"
            />

            <q-select
              outlined
              dark
              dense
              v-model="listForm.visibility"
              :options="visibilityOptions"
              :label="$t('adminUsers.visibility')"
              lazy-rules
              :rules="[(val) => val || $t('adminUsers.visibilityRequired')]"
            />

            <q-input
              outlined
              dark
              dense
              v-model="listForm.tags"
              :label="$t('adminUsers.tags')"
              :hint="$t('adminUsers.tagsHint')"
            />

            <q-toggle v-model="listForm.auto_update" :label="$t('adminUsers.autoUpdate')" />

            <q-input
              v-if="listForm.auto_update"
              outlined
              dark
              dense
              v-model="listForm.update_source"
              :label="$t('adminUsers.updateSource')"
              :hint="$t('adminUsers.updateSourceHint')"
            />
          </q-form>
        </q-card-section>

        <q-card-actions align="right" class="text-primary">
          <q-btn flat :label="$t('common.cancel')" @click="cancelListEdit" />
          <q-btn flat :label="$t('common.save')" @click="saveList" :loading="listSaving" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- User Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="$t('adminUsers.deleteConfirm')"
      :loading="deleting"
      @confirm="deleteUser"
    />

    <!-- List Delete Confirmation Dialog -->
    <ConfirmDeleteDialog
      v-model="showDeleteListDialog"
      :message="$t('adminUsers.deleteListConfirm')"
      :loading="listDeleting"
      @confirm="deleteList"
    />

    <!-- List Items View Dialog -->
    <q-dialog v-model="showListItemsDialog" persistent maximized>
      <q-card dark>
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">{{ $t('adminUsers.itemsTitle', { name: selectedList?.name }) }}</div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense @click="showListItemsDialog = false" />
        </q-card-section>

        <q-card-section class="q-pa-none" style="max-height: 70vh">
          <q-list bordered separator>
            <q-item v-for="item in listItems" :key="item.guid" class="q-pa-md">
              <q-item-section avatar>
                <q-avatar color="primary" text-color="white">
                  {{ item.item_type.charAt(0).toUpperCase() }}
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ item.item_data?.title || $t('common.unknown') }}</q-item-label>
                <q-item-label caption
                  >{{ $t('adminUsers.itemType') }}: {{ item.item_type }}</q-item-label
                >
                <q-item-label caption v-if="item.notes"
                  >{{ $t('adminUsers.itemNotes') }}: {{ item.notes }}</q-item-label
                >
              </q-item-section>
              <q-item-section side>
                <q-item-label caption
                  >{{ $t('adminUsers.itemAdded') }}:
                  {{ new Date(item.created_at).toLocaleDateString() }}</q-item-label
                >
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { useRouter } from 'vue-router'
import { logger } from 'src/utils/logger'
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

const listSaving = ref(false)
const listDeleting = ref(false)
const showCreateListDialog = ref(false)
const showDeleteListDialog = ref(false)
const showListItemsDialog = ref(false)
const listEditMode = ref(false)
const listToDelete = ref(null)
const selectedList = ref(null)
const listItems = ref([])

const listForm = ref({
  name: '',
  description: '',
  list_type: 'user',
  visibility: 'private',
  auto_update: false,
  update_source: '',
  tags: '',
})

const listTypes = ['user', 'system']
const visibilityOptions = ['private', 'public', 'unlisted']

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

function cancelListEdit() {
  showCreateListDialog.value = false
  listEditMode.value = false
  listForm.value = {
    name: '',
    description: '',
    list_type: 'user',
    visibility: 'private',
    auto_update: false,
    update_source: '',
    tags: '',
  }
}

async function saveList() {
  listSaving.value = true
  try {
    const listData = {
      name: listForm.value.name,
      description: listForm.value.description,
      list_type: listForm.value.list_type,
      visibility: listForm.value.visibility,
      auto_update: listForm.value.auto_update,
      update_source: listForm.value.update_source,
      tags: listForm.value.tags,
    }

    if (listEditMode.value) {
      await api.put(`/api/lists/${listForm.value.guid}`, listData)
    } else {
      await api.post('/api/lists', listData)
    }

    cancelListEdit()
  } catch (error) {
    logger.error('Error saving list:', error)
  } finally {
    listSaving.value = false
  }
}

async function deleteList() {
  listDeleting.value = true
  try {
    await api.delete(`/api/lists/${listToDelete.value.guid}`)
    showDeleteListDialog.value = false
    listToDelete.value = null
  } catch (error) {
    logger.error('Error deleting list:', error)
  } finally {
    listDeleting.value = false
  }
}

onMounted(() => {
  refresh()
})
</script>
