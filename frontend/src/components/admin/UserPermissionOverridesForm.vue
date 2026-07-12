<template>
  <q-card class="q-mt-md">
    <q-card-section>
      <div class="text-h6">
        <q-icon name="mdi-shield-account" class="q-mr-sm" />
        {{ $t('editUser.permissionOverrides') }}
      </div>
      <div class="text-caption text-grey">
        {{ $t('editUser.permissionOverridesHint') }}
      </div>
    </q-card-section>

    <q-separator />

    <q-card-section>
      <q-form @submit="savePermissionOverrides" class="q-gutter-md">
        <!-- Library Access -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.libraryAccess') }}</div>
        <q-select
          v-model="permOverrides.allowed_libraries"
          :options="libraryOptions"
          :label="$t('adminGroups.allowedLibraries')"
          outlined
          dense
          multiple
          use-chips
          clearable
          :hint="$t('editUser.inheritHint')"
        />

        <q-separator class="q-my-md" />

        <!-- Streaming Limits -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.streamingLimits') }}</div>
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-6">
            <q-input
              v-model.number="permOverrides.max_concurrent_streams"
              :label="$t('adminGroups.maxConcurrentStreams')"
              outlined
              dense
              type="number"
              min="0"
              clearable
              :hint="$t('editUser.inheritHint')"
            />
          </div>
          <div class="col-12 col-md-6">
            <q-input
              v-model.number="permOverrides.max_game_streams"
              :label="$t('adminGroups.maxGameStreams')"
              outlined
              dense
              type="number"
              min="0"
              clearable
              :hint="$t('editUser.inheritHint')"
            />
          </div>
        </div>

        <q-separator class="q-my-md" />

        <!-- Quality Limits -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.qualityLimits') }}</div>
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-6">
            <q-select
              v-model="permOverrides.max_video_quality"
              :options="videoQualityOptions"
              :label="$t('adminGroups.maxVideoQuality')"
              outlined
              dense
              emit-value
              map-options
              clearable
              :hint="$t('editUser.inheritHint')"
            />
          </div>
          <div class="col-12 col-md-6">
            <q-select
              v-model="permOverrides.max_audio_quality"
              :options="audioQualityOptions"
              :label="$t('adminGroups.maxAudioQuality')"
              outlined
              dense
              emit-value
              map-options
              clearable
              :hint="$t('editUser.inheritHint')"
            />
          </div>
        </div>

        <q-separator class="q-my-md" />

        <!-- Transcoding -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.features') }}</div>
        <q-input
          v-model.number="permOverrides.max_concurrent_transcodings"
          :label="$t('adminGroups.maxConcurrentTranscodings')"
          outlined
          dense
          type="number"
          min="0"
          clearable
          :hint="$t('editUser.inheritHint')"
        />

        <!-- Download Limits -->
        <LimitPeriodPair
          v-model:limit="permOverrides.offline_download_limit"
          v-model:period="permOverrides.offline_download_period_minutes"
          :limit-label="$t('adminGroups.offlineDownloadLimit')"
          :period-label="$t('adminGroups.period')"
          :hint="$t('editUser.inheritHint')"
          :period-options="periodOptions"
        />

        <LimitPeriodPair
          v-model:limit="permOverrides.prefetch_limit"
          v-model:period="permOverrides.prefetch_period_minutes"
          :limit-label="$t('adminGroups.prefetchLimit')"
          :period-label="$t('adminGroups.period')"
          :hint="$t('editUser.inheritHint')"
          :period-options="periodOptions"
        />

        <LimitPeriodPair
          v-model:limit="permOverrides.on_demand_fetch_limit"
          v-model:period="permOverrides.on_demand_fetch_period_minutes"
          :limit-label="$t('adminGroups.onDemandFetchLimit')"
          :period-label="$t('adminGroups.period')"
          :hint="$t('editUser.inheritHint')"
          :period-options="periodOptions"
        />

        <q-separator class="q-my-md" />

        <!-- Indexer Limits -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.indexerLimits') }}</div>
        <LimitPeriodPair
          v-model:limit="permOverrides.indexer_api_requests_limit"
          v-model:period="permOverrides.indexer_api_requests_period_minutes"
          :limit-label="$t('adminGroups.indexerApiRequestsLimit')"
          :period-label="$t('adminGroups.period')"
          :hint="$t('editUser.inheritHint')"
          :period-options="periodOptions"
          row-class=""
        />

        <LimitPeriodPair
          v-model:limit="permOverrides.indexer_downloads_limit"
          v-model:period="permOverrides.indexer_downloads_period_minutes"
          :limit-label="$t('adminGroups.indexerDownloadsLimit')"
          :period-label="$t('adminGroups.period')"
          :hint="$t('editUser.inheritHint')"
          :period-options="periodOptions"
        />

        <q-separator class="q-my-md" />

        <!-- Playback Limits -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.playbackLimits') }}</div>
        <LimitPeriodPair
          v-model:limit="permOverrides.playback_limit"
          v-model:period="permOverrides.playback_period_minutes"
          :limit-label="$t('adminGroups.playbackLimit')"
          :period-label="$t('adminGroups.period')"
          :hint="$t('editUser.inheritHint')"
          :period-options="periodOptions"
          row-class=""
        />

        <q-separator class="q-my-md" />

        <!-- Favorites -->
        <div class="text-subtitle1 q-mb-sm">{{ $t('adminGroups.favoritesSettings') }}</div>
        <q-toggle
          v-model="permOverrides.favorites_permanent"
          :label="$t('adminGroups.favoritesPermanent')"
          :hint="$t('editUser.inheritHint')"
        />

        <div class="row q-gutter-sm q-mt-md">
          <q-btn
            type="submit"
            color="primary"
            :label="$t('editUser.savePermissions')"
            :loading="permLoading"
          />
          <q-btn
            color="warning"
            :label="$t('editUser.resetPermissions')"
            @click="resetPermissionOverrides"
          />
        </div>
      </q-form>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'
import {
  getUserPermissionOverrides,
  updateUserPermissionOverrides,
} from 'src/services/accessAdminService'
import LimitPeriodPair from 'src/components/admin/LimitPeriodPair.vue'
import {
  LIBRARY_OPTIONS,
  VIDEO_QUALITY_OPTIONS,
  buildAudioQualityOptions,
  buildPeriodOptions,
} from 'src/utils/userEditOptions'

const props = defineProps({
  userGuid: { type: String, required: true },
})

const emit = defineEmits(['saved'])

const { t } = useI18n()
const $q = useQuasar()

const EMPTY_PERMISSION_OVERRIDES = Object.freeze({
  allowed_libraries: null,
  max_concurrent_streams: null,
  max_game_streams: null,
  max_video_quality: null,
  max_audio_quality: null,
  max_concurrent_transcodings: null,
  offline_download_limit: null,
  offline_download_period_minutes: null,
  prefetch_limit: null,
  prefetch_period_minutes: null,
  on_demand_fetch_limit: null,
  on_demand_fetch_period_minutes: null,
  indexer_api_requests_limit: null,
  indexer_api_requests_period_minutes: null,
  indexer_downloads_limit: null,
  indexer_downloads_period_minutes: null,
  playback_limit: null,
  playback_period_minutes: null,
  favorites_permanent: null,
})

const permLoading = ref(false)
const permOverrides = ref({ ...EMPTY_PERMISSION_OVERRIDES })

const libraryOptions = LIBRARY_OPTIONS
const videoQualityOptions = VIDEO_QUALITY_OPTIONS
const audioQualityOptions = buildAudioQualityOptions(t)
const periodOptions = buildPeriodOptions(t)

const loadPermissionOverrides = async () => {
  try {
    permOverrides.value = await getUserPermissionOverrides(props.userGuid)
  } catch (error) {
    logger.error('Error loading permission overrides:', error)
  }
}

const savePermissionOverrides = async () => {
  try {
    permLoading.value = true
    await updateUserPermissionOverrides(props.userGuid, permOverrides.value)
    $q.notify({ type: 'positive', message: t('editUser.permissionsSaved') })
    emit('saved')
  } catch (error) {
    logger.error('Error saving permission overrides:', error)
    $q.notify({ type: 'negative', message: t('editUser.permissionsSaveError') })
  } finally {
    permLoading.value = false
  }
}

const resetPermissionOverrides = async () => {
  permOverrides.value = { ...EMPTY_PERMISSION_OVERRIDES }
  await savePermissionOverrides()
}

onMounted(loadPermissionOverrides)
</script>
