<template>
  <q-page class="q-pa-md">
    <!-- Header -->
    <div class="row q-mb-lg items-center">
      <q-btn flat round icon="mdi-arrow-left" @click="router.back()" class="q-mr-sm" />
      <h4 class="q-my-none">
        {{ isEditing ? $t('adminBanners.editBanner') : $t('adminBanners.createBanner') }}
      </h4>
    </div>

    <!-- Loading -->
    <div v-if="loadingBanner" class="flex flex-center" style="min-height: 300px">
      <q-spinner color="primary" size="3em" />
    </div>

    <!-- Form -->
    <q-card v-else style="max-width: 800px">
      <q-card-section>
        <q-form @submit.prevent="saveBanner" class="q-gutter-md">
          <q-input
            v-model="form.title"
            :label="$t('adminBanners.bannerTitle')"
            :rules="[(val) => !!val || $t('adminBanners.titleRequired')]"
            maxlength="200"
            counter
            outlined
          />

          <q-input
            v-model="form.message"
            :label="$t('adminBanners.bannerMessage')"
            :rules="[(val) => !!val || $t('adminBanners.messageRequired')]"
            type="textarea"
            maxlength="2000"
            counter
            outlined
            rows="4"
          />

          <q-select
            v-model="form.banner_type"
            :options="bannerTypeOptions"
            :label="$t('adminBanners.bannerType')"
            option-value="value"
            option-label="label"
            emit-value
            map-options
            outlined
          />

          <q-toggle
            v-model="form.is_active"
            :label="$t('adminBanners.isActive')"
            color="positive"
          />

          <div class="text-subtitle2">{{ $t('adminBanners.schedule') }}</div>

          <q-input
            v-model="form.start_date"
            :label="$t('adminBanners.startDate')"
            outlined
            type="datetime-local"
            clearable
            :hint="$t('adminBanners.startDateHint')"
          />

          <q-input
            v-model="form.end_date"
            :label="$t('adminBanners.endDate')"
            outlined
            type="datetime-local"
            clearable
            :hint="$t('adminBanners.endDateHint')"
          />

          <!-- Preview -->
          <div class="text-subtitle2 q-mt-md">{{ $t('adminBanners.preview') }}</div>
          <q-banner
            :class="`bg-${getTypeColor(form.banner_type)}`"
            class="text-white rounded-borders"
          >
            <template v-slot:avatar>
              <q-icon :name="getTypeIcon(form.banner_type)" />
            </template>
            <div class="text-weight-bold">{{ form.title || $t('adminBanners.bannerTitle') }}</div>
            <div>{{ form.message || $t('adminBanners.bannerMessage') }}</div>
          </q-banner>

          <!-- Actions -->
          <div class="row justify-end q-gutter-sm q-mt-md">
            <q-btn flat :label="$t('common.cancel')" color="grey-7" @click="router.back()" />
            <q-btn
              type="submit"
              :label="$t('common.save')"
              color="primary"
              icon="mdi-content-save"
              :loading="saving"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import { getBanner, createBanner, updateBanner } from 'src/services/contentAdminService'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()

const saving = ref(false)
const loadingBanner = ref(false)

const bannerGuid = computed(() => route.params.guid)
const isEditing = computed(() => !!bannerGuid.value)

const form = ref({
  title: '',
  message: '',
  banner_type: 'info',
  is_active: true,
  start_date: null,
  end_date: null,
})

const bannerTypeOptions = computed(() => [
  { value: 'info', label: t('adminBanners.types.info') },
  { value: 'warning', label: t('adminBanners.types.warning') },
  { value: 'error', label: t('adminBanners.types.error') },
  { value: 'success', label: t('adminBanners.types.success') },
])

const getTypeColor = (type) => {
  const colors = { info: 'info', warning: 'warning', error: 'negative', success: 'positive' }
  return colors[type] || 'info'
}

const getTypeIcon = (type) => {
  const icons = {
    info: 'mdi-information',
    warning: 'mdi-alert',
    error: 'mdi-alert-circle',
    success: 'mdi-check-circle',
  }
  return icons[type] || 'mdi-information'
}

const formatForInput = (dateString) => {
  const date = new Date(dateString)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day}T${hours}:${minutes}`
}

const loadBanner = async () => {
  if (!bannerGuid.value) return
  loadingBanner.value = true
  try {
    const banner = await getBanner(bannerGuid.value)
    form.value = {
      title: banner.title,
      message: banner.message,
      banner_type: banner.banner_type,
      is_active: banner.is_active,
      start_date: banner.start_date ? formatForInput(banner.start_date) : null,
      end_date: banner.end_date ? formatForInput(banner.end_date) : null,
    }
  } catch (error) {
    logger.error('Error loading banner:', error)
    router.replace('/admin/banners')
  } finally {
    loadingBanner.value = false
  }
}

const saveBanner = async () => {
  saving.value = true
  try {
    const data = {
      ...form.value,
      start_date: form.value.start_date ? new Date(form.value.start_date).toISOString() : null,
      end_date: form.value.end_date ? new Date(form.value.end_date).toISOString() : null,
    }

    if (isEditing.value) {
      await updateBanner(bannerGuid.value, data)
    } else {
      await createBanner(data)
    }
    router.push('/admin/banners')
  } catch (error) {
    logger.error('Error saving banner:', error)
  } finally {
    saving.value = false
  }
}

onMounted(() => loadBanner())
</script>
