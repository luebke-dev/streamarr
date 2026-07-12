<template>
  <div class="col-12">
    <q-card class="settings-card">
      <q-card-section>
        <div class="text-h6 q-mb-md">
          <q-icon name="mdi-shield-lock" class="q-mr-sm" />
          {{ $t('adminSettings.permissions.title') }}
        </div>
        <p class="text-grey-6 q-mb-md">
          {{ $t('adminSettings.permissions.description') }}
        </p>

        <q-form @submit="savePermissionDefaults" class="q-gutter-md">
          <!-- Library Access -->
          <div class="text-subtitle2">{{ $t('adminGroups.libraryAccess') }}</div>
          <q-select
            v-model="permDefaults.allowed_libraries"
            :options="libraryOptions"
            :label="$t('adminGroups.allowedLibraries')"
            outlined
            dense
            multiple
            use-chips
            :disable="saving"
          />

          <!-- Streaming Limits -->
          <div class="text-subtitle2 q-mt-md">{{ $t('adminGroups.streamingLimits') }}</div>
          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-4">
              <q-input
                v-model.number="permDefaults.max_concurrent_streams"
                :label="$t('adminGroups.maxConcurrentStreams')"
                outlined
                dense
                type="number"
                min="0"
                :disable="saving"
              />
            </div>
            <div class="col-12 col-md-4">
              <q-input
                v-model.number="permDefaults.max_game_streams"
                :label="$t('adminGroups.maxGameStreams')"
                outlined
                dense
                type="number"
                min="0"
                :disable="saving"
              />
            </div>
            <div class="col-12 col-md-4">
              <q-input
                v-model.number="permDefaults.max_concurrent_transcodings"
                :label="$t('adminGroups.maxConcurrentTranscodings')"
                outlined
                dense
                type="number"
                min="0"
                :disable="saving"
              />
            </div>
          </div>

          <!-- Quality Limits -->
          <div class="text-subtitle2 q-mt-md">{{ $t('adminGroups.qualityLimits') }}</div>
          <div class="row q-col-gutter-md">
            <div class="col-12 col-md-6">
              <q-select
                v-model="permDefaults.max_video_quality"
                :options="videoQualityOptions"
                :label="$t('adminGroups.maxVideoQuality')"
                outlined
                dense
                emit-value
                map-options
                :disable="saving"
              />
            </div>
            <div class="col-12 col-md-6">
              <q-select
                v-model="permDefaults.max_audio_quality"
                :options="audioQualityOptions"
                :label="$t('adminGroups.maxAudioQuality')"
                outlined
                dense
                emit-value
                map-options
                :disable="saving"
              />
            </div>
          </div>

          <q-btn
            type="submit"
            color="primary"
            :label="$t('adminSettings.permissions.save')"
            :loading="saving"
            class="q-mt-md"
          />
        </q-form>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  getPermissionDefaults,
  savePermissionDefaults as savePermissionDefaultsApi,
} from 'src/services/systemAdminService'
import {
  LIBRARY_OPTIONS,
  VIDEO_QUALITY_OPTIONS,
  buildAudioQualityOptions,
} from 'src/utils/userEditOptions'

const { t } = useI18n()

const saving = ref(false)

const permDefaults = ref({
  allowed_libraries: ['movies', 'series', 'games', 'books', 'music'],
  max_concurrent_streams: 3,
  max_game_streams: 1,
  max_video_quality: 'uhd',
  max_audio_quality: 'lossless',
  max_concurrent_transcodings: 2,
})

const libraryOptions = LIBRARY_OPTIONS

const videoQualityOptions = VIDEO_QUALITY_OPTIONS

const audioQualityOptions = buildAudioQualityOptions(t)

const loadPermissionDefaults = async () => {
  try {
    const data = await getPermissionDefaults()
    permDefaults.value = data
  } catch (error) {
    logger.error('Failed to load permission defaults:', error)
  }
}

const savePermissionDefaults = async () => {
  saving.value = true
  try {
    const data = await savePermissionDefaultsApi(permDefaults.value)
    permDefaults.value = data
  } catch (error) {
    logger.error('Failed to save permission defaults:', error)
  } finally {
    saving.value = false
  }
}

onMounted(loadPermissionDefaults)

defineExpose({ reload: loadPermissionDefaults })
</script>

<style lang="scss" scoped>
.settings-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
