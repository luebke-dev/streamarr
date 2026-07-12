<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminGroups.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminGroups.subtitle') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model="search"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
              @update:model-value="filterGroups"
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
              :label="$t('adminGroups.createGroup')"
              @click="$router.push('/admin/groups/create')"
            />
          </div>
        </div>

        <q-table
          flat
          bordered
          dark
          :rows="filteredGroups"
          :columns="columns"
          :loading="loading"
          row-key="guid"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
        >
          <template v-slot:body-cell-name="props">
            <q-td :props="props">
              <div class="text-weight-medium">{{ props.row.name }}</div>
              <div v-if="props.row.description" class="text-caption text-grey-7">
                {{ props.row.description }}
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-is_active="props">
            <q-td :props="props">
              <q-chip :color="props.value ? 'positive' : 'grey'" text-color="white" size="sm" dense>
                {{ props.value ? $t('common.active') : $t('common.inactive') }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-permissions="props">
            <q-td :props="props">
              <div class="row q-gutter-xs">
                <q-chip
                  v-if="props.row.allowed_libraries.length > 0"
                  size="sm"
                  dense
                  color="blue"
                  text-color="white"
                >
                  <q-icon name="mdi-library" size="xs" class="q-mr-xs" />
                  {{ props.row.allowed_libraries.length }}
                </q-chip>
                <q-chip
                  v-if="props.row.max_concurrent_streams > 0"
                  size="sm"
                  dense
                  color="accent"
                  text-color="white"
                >
                  <q-icon name="mdi-play-circle" size="xs" class="q-mr-xs" />
                  {{ props.row.max_concurrent_streams }}
                </q-chip>
                <q-chip
                  v-if="props.row.allow_transcoding"
                  size="sm"
                  dense
                  color="orange"
                  text-color="white"
                >
                  <q-icon name="mdi-cog" size="xs" />
                </q-chip>
              </div>
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
                @click="$router.push(`/admin/groups/${props.row.guid}/edit`)"
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
      :message="$t('adminGroups.confirmDelete')"
      :loading="deleting"
      @confirm="deleteGroup"
    />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'
import { getGroups, deleteGroup as deleteGroupRequest } from 'src/services/accessAdminService'

const { t } = useI18n()

const groups = ref([])
const loading = ref(false)
const search = ref('')
const showDeleteDialog = ref(false)
const deleting = ref(false)
const selectedGroup = ref(null)

const columns = computed(() => [
  {
    name: 'name',
    required: true,
    label: t('adminGroups.name'),
    align: 'left',
    field: 'name',
    sortable: true,
  },
  {
    name: 'member_count',
    label: t('adminGroups.members'),
    align: 'left',
    field: 'member_count',
    sortable: true,
  },
  {
    name: 'permissions',
    label: t('adminGroups.permissions'),
    align: 'left',
    field: 'permissions',
  },
  {
    name: 'is_active',
    label: t('adminGroups.status'),
    align: 'left',
    field: 'is_active',
    sortable: true,
  },
  {
    name: 'actions',
    label: t('common.actions'),
    align: 'center',
    field: 'actions',
  },
])

const filteredGroups = computed(() => {
  if (!search.value) return groups.value

  const searchLower = search.value.toLowerCase()
  return groups.value.filter(
    (group) =>
      group.name.toLowerCase().includes(searchLower) ||
      (group.description && group.description.toLowerCase().includes(searchLower)),
  )
})

const loadGroups = async () => {
  loading.value = true
  try {
    groups.value = await getGroups()
  } catch (error) {
    logger.error('Failed to load groups:', error)
  } finally {
    loading.value = false
  }
}

const filterGroups = () => {
  // Trigger reactivity
}

const confirmDelete = (group) => {
  selectedGroup.value = group
  showDeleteDialog.value = true
}

const deleteGroup = async () => {
  if (!selectedGroup.value) return

  deleting.value = true
  try {
    await deleteGroupRequest(selectedGroup.value.guid)

    showDeleteDialog.value = false
    selectedGroup.value = null
    loadGroups()
  } catch (error) {
    logger.error('Failed to delete group:', error)
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  loadGroups()
})
</script>

<style scoped>
.q-chip {
  font-weight: 500;
}
</style>
