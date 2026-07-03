<template>
  <q-card class="q-mt-md">
    <q-card-section>
      <div class="text-h6">
        <q-icon name="mdi-skip-forward" class="q-mr-sm" />
        {{ t('editUser.playbackPreferences') }}
      </div>
      <div class="text-caption text-grey">
        {{ t('editUser.playbackPreferencesHint') }}
      </div>
    </q-card-section>

    <q-separator />

    <q-card-section>
      <q-form @submit="savePlaybackPreferences" class="q-gutter-md">
        <q-select
          v-model="playbackPrefs.skip_intro_mode"
          :options="skipModeOptions"
          :label="t('settings.skipIntro')"
          outlined
          dense
          emit-value
          map-options
          option-value="value"
          option-label="label"
        />

        <q-select
          v-model="playbackPrefs.skip_outro_mode"
          :options="skipModeOptions"
          :label="t('settings.skipOutro')"
          outlined
          dense
          emit-value
          map-options
          option-value="value"
          option-label="label"
        />

        <q-select
          v-model="playbackPrefs.skip_credits_mode"
          :options="skipModeOptions"
          :label="t('settings.skipCredits')"
          outlined
          dense
          emit-value
          map-options
          option-value="value"
          option-label="label"
        />

        <q-btn
          type="submit"
          color="primary"
          :label="t('editUser.savePlaybackPreferences')"
          :loading="loading"
        />
      </q-form>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const props = defineProps({
  userGuid: {
    type: String,
    required: true,
  },
})

const { t } = useI18n()
const $q = useQuasar()

const loading = ref(false)
const playbackPrefs = ref({
  skip_intro_mode: 'button',
  skip_outro_mode: 'button',
  skip_credits_mode: 'button',
})

const skipModeOptions = [
  { value: 'button', label: t('settings.skipModeButton') },
  { value: 'auto', label: t('settings.skipModeAuto') },
  { value: 'disabled', label: t('settings.skipModeDisabled') },
]

const loadPlaybackPreferences = async () => {
  try {
    const response = await api.get(`/api/users/${props.userGuid}/playback-preferences`)
    playbackPrefs.value = response.data
  } catch (error) {
    logger.error('Error loading playback preferences:', error)
  }
}

const savePlaybackPreferences = async () => {
  try {
    loading.value = true
    await api.put(`/api/users/${props.userGuid}/playback-preferences`, playbackPrefs.value)
    $q.notify({ type: 'positive', message: t('editUser.playbackPreferencesSaved') })
  } catch (error) {
    logger.error('Error saving playback preferences:', error)
    $q.notify({ type: 'negative', message: t('editUser.playbackPreferencesSaveError') })
  } finally {
    loading.value = false
  }
}

onMounted(loadPlaybackPreferences)
</script>
