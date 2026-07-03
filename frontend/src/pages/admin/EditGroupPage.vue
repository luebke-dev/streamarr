<template>
  <q-page padding>
    <div class="row justify-center">
      <div class="col-12 col-md-10 col-lg-8">
        <q-card>
          <q-card-section>
            <div class="text-h5">
              {{ isCreateMode ? $t('adminGroups.createGroup') : $t('adminGroups.editGroup') }}
            </div>
          </q-card-section>

          <q-separator />

          <q-card-section>
            <q-form @submit="saveGroup" class="q-gutter-md">
              <!-- Basic Information -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.basicInfo') }}</div>

              <q-input
                v-model="formData.name"
                :label="$t('adminGroups.name')"
                outlined
                dense
                :rules="[(val) => !!val || $t('adminGroups.nameRequired')]"
              />

              <q-input
                v-model="formData.description"
                :label="$t('adminGroups.description')"
                outlined
                dense
                type="textarea"
                rows="3"
              />

              <q-toggle v-model="formData.is_active" :label="$t('adminGroups.isActive')" />

              <q-separator class="q-my-lg" />

              <!-- Library Access -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.libraryAccess') }}</div>

              <q-select
                v-model="formData.allowed_libraries"
                :options="libraryOptions"
                :label="$t('adminGroups.allowedLibraries')"
                outlined
                dense
                multiple
                use-chips
              />

              <q-separator class="q-my-lg" />

              <!-- Streaming Limits -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.streamingLimits') }}</div>

              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6">
                  <q-input
                    v-model.number="formData.max_concurrent_streams"
                    :label="$t('adminGroups.maxConcurrentStreams')"
                    outlined
                    dense
                    type="number"
                    min="0"
                  />
                </div>
                <div class="col-12 col-md-6">
                  <q-input
                    v-model.number="formData.max_game_streams"
                    :label="$t('adminGroups.maxGameStreams')"
                    outlined
                    dense
                    type="number"
                    min="0"
                  />
                </div>
              </div>

              <q-separator class="q-my-lg" />

              <!-- Quality Limits -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.qualityLimits') }}</div>

              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6">
                  <q-select
                    v-model="formData.max_video_quality"
                    :options="videoQualityOptions"
                    :label="$t('adminGroups.maxVideoQuality')"
                    outlined
                    dense
                    emit-value
                    map-options
                    clearable
                  />
                </div>
                <div class="col-12 col-md-6">
                  <q-select
                    v-model="formData.max_audio_quality"
                    :options="audioQualityOptions"
                    :label="$t('adminGroups.maxAudioQuality')"
                    outlined
                    dense
                    emit-value
                    map-options
                    clearable
                  />
                </div>
              </div>

              <q-separator class="q-my-lg" />

              <!-- Features -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.features') }}</div>

              <div class="row q-col-gutter-md">
                <div class="col-12">
                  <q-input
                    v-model.number="formData.max_concurrent_transcodings"
                    :label="$t('adminGroups.maxConcurrentTranscodings')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    :hint="$t('adminGroups.transcodingHint')"
                  />
                </div>
              </div>

              <!-- Offline Download Limits -->
              <div class="row q-col-gutter-md q-mt-sm">
                <div class="col-8">
                  <q-input
                    v-model.number="formData.offline_download_limit"
                    :label="$t('adminGroups.offlineDownloadLimit')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    clearable
                    :hint="$t('adminGroups.unlimitedHint')"
                  />
                </div>
                <div class="col-4">
                  <q-select
                    v-model="formData.offline_download_period_minutes"
                    :options="periodOptions"
                    :label="$t('adminGroups.period')"
                    outlined
                    dense
                    emit-value
                    map-options
                  />
                </div>
              </div>

              <!-- Prefetch Limits -->
              <div class="row q-col-gutter-md q-mt-sm">
                <div class="col-8">
                  <q-input
                    v-model.number="formData.prefetch_limit"
                    :label="$t('adminGroups.prefetchLimit')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    clearable
                    :hint="$t('adminGroups.unlimitedHint')"
                  />
                </div>
                <div class="col-4">
                  <q-select
                    v-model="formData.prefetch_period_minutes"
                    :options="periodOptions"
                    :label="$t('adminGroups.period')"
                    outlined
                    dense
                    emit-value
                    map-options
                  />
                </div>
              </div>

              <!-- On-Demand Fetch Limits -->
              <div class="row q-col-gutter-md q-mt-sm">
                <div class="col-8">
                  <q-input
                    v-model.number="formData.on_demand_fetch_limit"
                    :label="$t('adminGroups.onDemandFetchLimit')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    clearable
                    :hint="$t('adminGroups.unlimitedHint')"
                  />
                </div>
                <div class="col-4">
                  <q-select
                    v-model="formData.on_demand_fetch_period_minutes"
                    :options="periodOptions"
                    :label="$t('adminGroups.period')"
                    outlined
                    dense
                    emit-value
                    map-options
                  />
                </div>
              </div>

              <q-separator class="q-my-lg" />

              <!-- Indexer Limits -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.indexerLimits') }}</div>

              <div class="row q-col-gutter-md">
                <div class="col-8">
                  <q-input
                    v-model.number="formData.indexer_api_requests_limit"
                    :label="$t('adminGroups.indexerApiRequestsLimit')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    clearable
                    :hint="$t('adminGroups.unlimitedHint')"
                  />
                </div>
                <div class="col-4">
                  <q-select
                    v-model="formData.indexer_api_requests_period_minutes"
                    :options="periodOptions"
                    :label="$t('adminGroups.period')"
                    outlined
                    dense
                    emit-value
                    map-options
                  />
                </div>
              </div>

              <div class="row q-col-gutter-md q-mt-sm">
                <div class="col-8">
                  <q-input
                    v-model.number="formData.indexer_downloads_limit"
                    :label="$t('adminGroups.indexerDownloadsLimit')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    clearable
                    :hint="$t('adminGroups.unlimitedHint')"
                  />
                </div>
                <div class="col-4">
                  <q-select
                    v-model="formData.indexer_downloads_period_minutes"
                    :options="periodOptions"
                    :label="$t('adminGroups.period')"
                    outlined
                    dense
                    emit-value
                    map-options
                  />
                </div>
              </div>

              <q-separator class="q-my-lg" />

              <!-- Playback Limits -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.playbackLimits') }}</div>

              <div class="row q-col-gutter-md">
                <div class="col-8">
                  <q-input
                    v-model.number="formData.playback_limit"
                    :label="$t('adminGroups.playbackLimit')"
                    outlined
                    dense
                    type="number"
                    min="0"
                    clearable
                    :hint="$t('adminGroups.unlimitedHint')"
                  />
                </div>
                <div class="col-4">
                  <q-select
                    v-model="formData.playback_period_minutes"
                    :options="periodOptions"
                    :label="$t('adminGroups.period')"
                    outlined
                    dense
                    emit-value
                    map-options
                  />
                </div>
              </div>

              <q-separator class="q-my-lg" />

              <!-- Favorites -->
              <div class="text-h6 q-mb-md">{{ $t('adminGroups.favoritesSettings') }}</div>

              <q-toggle
                v-model="formData.favorites_permanent"
                :label="$t('adminGroups.favoritesPermanent')"
              />

              <q-separator class="q-my-lg" />

              <!-- Actions -->
              <div class="row q-gutter-sm">
                <q-btn type="submit" color="primary" :label="$t('common.save')" :loading="saving" />
                <q-btn flat :label="$t('common.cancel')" @click="$router.push('/admin/groups')" />
              </div>
            </q-form>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import {
  LIBRARY_OPTIONS,
  VIDEO_QUALITY_OPTIONS,
  buildAudioQualityOptions,
  buildPeriodOptions,
} from 'src/utils/userEditOptions'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()

const groupId = computed(() => route.params.id)
const isCreateMode = computed(() => !groupId.value)

const saving = ref(false)
const formData = ref({
  name: '',
  description: '',
  is_active: true,
  allowed_libraries: [],
  max_concurrent_streams: 1,
  max_game_streams: 0,
  offline_download_limit: null,
  offline_download_period_minutes: 1440,
  prefetch_limit: null,
  prefetch_period_minutes: 1440,
  on_demand_fetch_limit: null,
  on_demand_fetch_period_minutes: 1440,
  max_video_quality: 'uhd',
  max_audio_quality: 'lossless',
  indexer_api_requests_limit: null,
  indexer_api_requests_period_minutes: 60,
  indexer_downloads_limit: null,
  indexer_downloads_period_minutes: 1440,
  playback_limit: null,
  playback_period_minutes: 1440,
  max_concurrent_transcodings: 1,
})

const libraryOptions = LIBRARY_OPTIONS

const videoQualityOptions = VIDEO_QUALITY_OPTIONS

const audioQualityOptions = computed(() => buildAudioQualityOptions(t))

const periodOptions = computed(() => buildPeriodOptions(t))

const loadGroup = async () => {
  if (isCreateMode.value) return

  try {
    const response = await api.get(`/api/groups/${groupId.value}`)
    const group = response.data

    formData.value = {
      name: group.name,
      description: group.description || '',
      is_active: group.is_active,
      allowed_libraries: group.allowed_libraries || [],
      max_concurrent_streams: group.max_concurrent_streams,
      max_game_streams: group.max_game_streams,
      offline_download_limit: group.offline_download_limit,
      offline_download_period_minutes: group.offline_download_period_minutes || 1440,
      prefetch_limit: group.prefetch_limit,
      prefetch_period_minutes: group.prefetch_period_minutes || 1440,
      on_demand_fetch_limit: group.on_demand_fetch_limit,
      on_demand_fetch_period_minutes: group.on_demand_fetch_period_minutes || 1440,
      max_video_quality: group.max_video_quality || 'uhd',
      max_audio_quality: group.max_audio_quality || 'lossless',
      indexer_api_requests_limit: group.indexer_api_requests_limit,
      indexer_api_requests_period_minutes: group.indexer_api_requests_period_minutes || 60,
      indexer_downloads_limit: group.indexer_downloads_limit,
      indexer_downloads_period_minutes: group.indexer_downloads_period_minutes || 1440,
      playback_limit: group.playback_limit,
      playback_period_minutes: group.playback_period_minutes || 1440,
      max_concurrent_transcodings: group.max_concurrent_transcodings || 1,
    }
  } catch (error) {
    logger.error('Failed to load group:', error)
    router.push('/admin/groups')
  }
}

const saveGroup = async () => {
  saving.value = true
  try {
    const payload = { ...formData.value }

    if (isCreateMode.value) {
      await api.post('/api/groups', payload)
    } else {
      await api.patch(`/api/groups/${groupId.value}`, payload)
    }

    router.push('/admin/groups')
  } catch (error) {
    logger.error('Failed to save group:', error)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadGroup()
})
</script>
