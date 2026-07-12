<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="col">
        <h4 class="q-my-none">{{ $t('adminMenu.pageLayouts', 'Page Layouts') }}</h4>
        <p class="text-grey-6 q-mt-sm q-mb-none">
          {{ $t('pageLayouts.description', 'Configure which sections appear on browse pages') }}
        </p>
      </div>
      <div class="col-auto">
        <q-btn color="primary" icon="mdi-plus" :label="$t('common.create')" @click="createLayout" />
      </div>
    </div>

    <q-table
      ref="tableRef"
      flat
      bordered
      dark
      :rows="layouts"
      :columns="columns"
      row-key="guid"
      :loading="loading"
      :pagination="pagination"
      @request="onRequest"
    >
      <template v-slot:body-cell-name="props">
        <q-td :props="props">
          <router-link
            :to="`/admin/page-layouts/${props.row.guid}`"
            class="text-primary text-weight-medium"
          >
            {{ props.row.name }}
          </router-link>
        </q-td>
      </template>

      <template v-slot:body-cell-slug="props">
        <q-td :props="props">
          <q-badge outline color="grey-7">{{ props.row.slug }}</q-badge>
        </q-td>
      </template>

      <template v-slot:body-cell-is_active="props">
        <q-td :props="props">
          <q-icon
            :name="props.row.is_active ? 'mdi-check-circle' : 'mdi-close-circle'"
            :color="props.row.is_active ? 'positive' : 'grey-5'"
            size="sm"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-section_count="props">
        <q-td :props="props">
          <q-badge color="primary">{{ props.row.section_count }}</q-badge>
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props" auto-width>
          <q-btn
            flat
            round
            dense
            icon="mdi-pencil"
            color="primary"
            @click="$router.push(`/admin/page-layouts/${props.row.guid}`)"
          />
          <q-btn
            flat
            round
            dense
            icon="mdi-delete"
            color="negative"
            @click="confirmDelete(props.row)"
            :disable="props.row.slug === 'home'"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Delete confirmation -->
    <q-dialog v-model="showDeleteDialog">
      <q-card dark style="min-width: 350px">
        <q-card-section class="row items-center">
          <q-avatar icon="mdi-alert" color="negative" text-color="white" />
          <span class="q-ml-sm">
            {{
              $t('pageLayouts.confirmDelete', 'Delete layout "{name}"?').replace(
                '{name}',
                layoutToDelete?.name,
              )
            }}
          </span>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn
            flat
            color="negative"
            :label="$t('common.delete')"
            @click="deleteLayout"
            :loading="deleting"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { getPageLayouts, deletePageLayout } from 'src/services/contentAdminService'

const router = useRouter()
const { t } = useI18n()

const tableRef = ref(null)
const layouts = ref([])
const loading = ref(false)
const showDeleteDialog = ref(false)
const layoutToDelete = ref(null)
const deleting = ref(false)

const pagination = ref({
  page: 1,
  rowsPerPage: 25,
  rowsNumber: 0,
})

const columns = computed(() => [
  { name: 'name', label: t('common.name', 'Name'), field: 'name', align: 'left', sortable: true },
  { name: 'slug', label: t('common.slug', 'Slug'), field: 'slug', align: 'left' },
  { name: 'is_active', label: t('common.active', 'Active'), field: 'is_active', align: 'center' },
  {
    name: 'section_count',
    label: t('pageLayouts.sections', 'Sections'),
    field: 'section_count',
    align: 'center',
  },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
])

async function onRequest() {
  loading.value = true
  try {
    const data = await getPageLayouts()
    layouts.value = data
    pagination.value.rowsNumber = data.length
  } catch (error) {
    logger.error('Error loading layouts:', error)
  } finally {
    loading.value = false
  }
}

function createLayout() {
  router.push('/admin/page-layouts/create')
}

function confirmDelete(layout) {
  layoutToDelete.value = layout
  showDeleteDialog.value = true
}

async function deleteLayout() {
  if (!layoutToDelete.value) return
  deleting.value = true
  try {
    await deletePageLayout(layoutToDelete.value.guid)
    showDeleteDialog.value = false
    tableRef.value.requestServerInteraction()
  } catch (error) {
    logger.error('Error deleting layout:', error)
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  tableRef.value.requestServerInteraction()
})
</script>
