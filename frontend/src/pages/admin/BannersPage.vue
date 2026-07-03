<template>
  <q-page class="q-pa-md">
    <div class="row items-center justify-between q-mb-md">
      <div class="text-h4">{{ $t('adminBanners.title') }}</div>
      <q-btn
        color="primary"
        icon="mdi-plus"
        :label="$t('adminBanners.createBanner')"
        no-caps
        @click="router.push('/admin/banners/create')"
      />
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex flex-center" style="min-height: 400px">
      <q-spinner color="primary" size="3em" />
    </div>

    <!-- Banners List -->
    <q-table
      v-else
      :rows="banners"
      :columns="columns"
      row-key="guid"
      :pagination="pagination"
      @request="onRequest"
      flat
      bordered
      dark
    >
      <template v-slot:body-cell-banner_type="props">
        <q-td :props="props">
          <q-chip
            :color="getTypeColor(props.row.banner_type)"
            text-color="white"
            dense
            :label="$t(`adminBanners.types.${props.row.banner_type}`)"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-is_active="props">
        <q-td :props="props">
          <q-toggle
            :model-value="props.row.is_active"
            @update:model-value="(val) => toggleActive(props.row, val)"
            color="positive"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-created_at="props">
        <q-td :props="props">
          {{ formatDate(props.row.created_at) }}
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
            @click="router.push(`/admin/banners/${props.row.guid}/edit`)"
          >
            <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat
            dense
            round
            icon="mdi-delete"
            color="negative"
            @click="confirmDelete(props.row)"
          >
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Delete Confirmation Dialog -->
    <q-dialog v-model="showDeleteDialog" persistent>
      <q-card dark>
        <q-card-section>
          <div class="text-h6">{{ $t('adminBanners.deleteBanner') }}</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          {{ $t('adminBanners.deleteConfirm') }}
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" color="grey-7" v-close-popup />
          <q-btn
            flat
            :label="$t('common.delete')"
            color="negative"
            :loading="deleting"
            @click="deleteBanner"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from 'boot/axios'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { formatDate } from 'src/composables/useMediaFormatters'

const { t } = useI18n()
const router = useRouter()

const loading = ref(false)
const deleting = ref(false)
const banners = ref([])
const showDeleteDialog = ref(false)
const bannerToDelete = ref(null)

const pagination = ref({
  page: 1,
  rowsPerPage: 25,
  rowsNumber: 0,
})

const columns = computed(() => [
  {
    name: 'title',
    label: t('adminBanners.bannerTitle'),
    field: 'title',
    align: 'left',
    sortable: true,
  },
  { name: 'banner_type', label: t('adminBanners.bannerType'), field: 'banner_type', align: 'left' },
  { name: 'is_active', label: t('adminBanners.isActive'), field: 'is_active', align: 'center' },
  {
    name: 'created_at',
    label: t('adminBanners.createdAt'),
    field: 'created_at',
    align: 'left',
    sortable: true,
  },
  { name: 'actions', label: t('common.actions'), align: 'center' },
])

const getTypeColor = (type) => {
  const colors = { info: 'info', warning: 'warning', error: 'negative', success: 'positive' }
  return colors[type] || 'info'
}

const loadBanners = async () => {
  loading.value = true
  try {
    const response = await api.get('/api/banners', {
      params: { page: pagination.value.page, per_page: pagination.value.rowsPerPage },
    })
    banners.value = response.data.items
    pagination.value.rowsNumber = response.data.total
  } catch (error) {
    logger.error('Error loading banners:', error)
  } finally {
    loading.value = false
  }
}

const onRequest = (props) => {
  pagination.value = props.pagination
  loadBanners()
}

const toggleActive = async (banner, value) => {
  try {
    await api.put(`/api/banners/${banner.guid}`, { is_active: value })
    banner.is_active = value
  } catch (error) {
    logger.error('Error updating banner:', error)
  }
}

const confirmDelete = (banner) => {
  bannerToDelete.value = banner
  showDeleteDialog.value = true
}

const deleteBanner = async () => {
  if (!bannerToDelete.value) return
  deleting.value = true
  try {
    await api.delete(`/api/banners/${bannerToDelete.value.guid}`)
    await loadBanners()
    showDeleteDialog.value = false
    bannerToDelete.value = null
  } catch (error) {
    logger.error('Error deleting banner:', error)
  } finally {
    deleting.value = false
  }
}

onMounted(() => loadBanners())
</script>
