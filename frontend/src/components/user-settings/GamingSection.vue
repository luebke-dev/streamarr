<template>
  <div class="q-mb-lg">
    <q-card flat bordered>
      <q-card-section>
        <div class="text-h6 q-mb-sm">
          <q-icon name="mdi-gamepad-variant" class="q-mr-sm" />
          {{ $t('settings.gaming') }}
        </div>
        <div class="text-body2 text-grey-6 q-mb-lg">
          {{ $t('settings.gamingDescription') }}
        </div>

        <div class="q-gutter-md">
          <div>
            <div class="text-subtitle2 q-mb-sm">
              <q-icon name="mdi-keyboard" class="q-mr-xs" />
              {{ $t('settings.keyboardLayout') }}
            </div>
            <q-select
              v-model="prefs.keyboard_layout"
              :options="keyboardLayoutOptions"
              option-value="value"
              option-label="label"
              emit-value
              map-options
              outlined
              dense
              :loading="updating"
              @update:model-value="save"
            >
              <template #selected-item="{ opt }">
                <div class="row items-center">
                  <span class="q-mr-xs">{{ opt.flag }}</span>
                  <span>{{ opt.label }}</span>
                </div>
              </template>
              <template #option="{ itemProps, opt }">
                <q-item v-bind="itemProps">
                  <q-item-section avatar>
                    <span class="text-h6">{{ opt.flag }}</span>
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>{{ opt.label }}</q-item-label>
                  </q-item-section>
                </q-item>
              </template>
            </q-select>
          </div>

          <div>
            <div class="text-subtitle2 q-mb-sm">
              <q-icon name="mdi-mouse" class="q-mr-xs" />
              {{ $t('settings.mouseSpeed') }}
              <span class="text-grey-6">({{ prefs.mouse_speed.toFixed(1) }}x)</span>
            </div>
            <q-slider
              v-model="prefs.mouse_speed"
              :min="0.1"
              :max="3.0"
              :step="0.1"
              label
              :label-value="`${prefs.mouse_speed.toFixed(1)}x`"
              label-always
              :disable="updating"
              @change="save"
            />
          </div>
        </div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from 'src/stores/auth'
import { logger } from 'src/utils/logger'

const authStore = useAuthStore()

const updating = ref(false)
const prefs = ref({
  keyboard_layout: 'us',
  mouse_speed: 1.0,
})

// XKB layout codes the user can pick from for cloud gaming sessions.
// Kept as an explicit whitelist rather than an exhaustive X11 layout list
// so the dropdown stays manageable — covers the common Moonlight/Wolf
// targets the backend-side GOW image actually supports out of the box.
const keyboardLayoutOptions = [
  { value: 'us', label: 'English (US)', flag: '🇺🇸' },
  { value: 'gb', label: 'English (UK)', flag: '🇬🇧' },
  { value: 'de', label: 'Deutsch', flag: '🇩🇪' },
  { value: 'fr', label: 'Français', flag: '🇫🇷' },
  { value: 'es', label: 'Español', flag: '🇪🇸' },
  { value: 'it', label: 'Italiano', flag: '🇮🇹' },
  { value: 'pt', label: 'Português', flag: '🇧🇷' },
  { value: 'ru', label: 'Русский', flag: '🇷🇺' },
  { value: 'jp', label: '日本語', flag: '🇯🇵' },
]

async function load() {
  try {
    const response = await authStore.fetchGamingPreferences()
    prefs.value = {
      keyboard_layout: response.keyboard_layout || 'us',
      mouse_speed: typeof response.mouse_speed === 'number' ? response.mouse_speed : 1.0,
    }
  } catch (e) {
    // Fall back to defaults; not user-impacting but should be diagnosable
    logger.warn('Failed to load gaming settings, using defaults', e)
  }
}

async function save() {
  updating.value = true
  try {
    const saved = await authStore.updateGamingPreferences({ ...prefs.value })
    // Reflect server-side clamping / defaults back into the UI so the
    // slider stays in sync with what the backend actually stored.
    prefs.value = {
      keyboard_layout: saved.keyboard_layout || 'us',
      mouse_speed: typeof saved.mouse_speed === 'number' ? saved.mouse_speed : 1.0,
    }
  } catch (error) {
    logger.error('Failed to update gaming preferences:', error)
  } finally {
    updating.value = false
  }
}

onMounted(load)
</script>
