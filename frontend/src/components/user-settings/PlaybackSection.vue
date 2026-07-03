<template>
  <div class="q-mb-lg">
    <q-card flat bordered>
      <q-card-section>
        <div class="text-h6 q-mb-sm">
          <q-icon name="mdi-skip-forward" class="q-mr-sm" />
          {{ $t('settings.playback') }}
        </div>
        <div class="text-body2 text-grey-6 q-mb-lg">
          {{ $t('settings.playbackDescription') }}
        </div>

        <div class="q-gutter-md">
          <div v-for="field in skipFields" :key="field.key">
            <div class="text-subtitle2 q-mb-sm">
              <q-icon :name="field.icon" class="q-mr-xs" />
              {{ $t(field.labelKey) }}
            </div>
            <q-select
              v-model="prefs[field.key]"
              :options="skipModeOptions"
              option-value="value"
              option-label="label"
              emit-value
              map-options
              outlined
              dense
              :loading="updating"
              @update:model-value="save"
            />
          </div>
        </div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from 'src/stores/auth'
import { logger } from 'src/utils/logger'

const { t } = useI18n()
const authStore = useAuthStore()

const updating = ref(false)
const prefs = ref({
  skip_intro_mode: 'button',
  skip_outro_mode: 'button',
  skip_credits_mode: 'button',
})

const skipModeOptions = computed(() => [
  { value: 'button', label: t('settings.skipModeButton') },
  { value: 'auto', label: t('settings.skipModeAuto') },
  { value: 'disabled', label: t('settings.skipModeDisabled') },
])

const skipFields = [
  { key: 'skip_intro_mode', icon: 'mdi-skip-next', labelKey: 'settings.skipIntro' },
  { key: 'skip_outro_mode', icon: 'mdi-skip-previous', labelKey: 'settings.skipOutro' },
  { key: 'skip_credits_mode', icon: 'mdi-movie-open', labelKey: 'settings.skipCredits' },
]

async function load() {
  try {
    const response = await authStore.fetchPlaybackPreferences()
    prefs.value = {
      skip_intro_mode: response.skip_intro_mode || 'button',
      skip_outro_mode: response.skip_outro_mode || 'button',
      skip_credits_mode: response.skip_credits_mode || 'button',
    }
  } catch (e) {
    // Fall back to defaults; not user-impacting but should be diagnosable
    logger.warn('Failed to load playback settings, using defaults', e)
  }
}

async function save() {
  updating.value = true
  try {
    await authStore.updatePlaybackPreferences({ ...prefs.value })
  } catch (error) {
    logger.error('Failed to update playback preferences:', error)
  } finally {
    updating.value = false
  }
}

onMounted(load)
</script>
