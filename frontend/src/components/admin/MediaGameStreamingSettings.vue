<template>
  <q-card v-if="isGame" flat bordered class="q-mt-xl game-streaming-settings">
    <q-card-section class="row items-center justify-between q-gutter-sm">
      <div class="text-h6 text-white">{{ $t('mediaDetail.gameStreaming') }}</div>
      <q-chip dense color="blue-grey-8" text-color="white">
        {{ runtimeLabel }}
      </q-chip>
    </q-card-section>

    <q-card-section class="row q-col-gutter-md items-start">
      <!-- Runtime selector: which container profile this game launches in -->
      <div class="col-12 col-md-6">
        <q-select
          v-model="runtime"
          :options="runtimeOptions"
          dense
          outlined
          dark
          clearable
          emit-value
          map-options
          :label="$t('mediaDetail.runtime')"
          :hint="$t('mediaDetail.runtimeHint')"
          :loading="loadingRuntimes"
        />
      </div>
      <!-- Optional launch target substituted into the runtime's {app_ref} -->
      <div class="col-12 col-md-6">
        <q-input
          v-model.trim="appRef"
          dense
          outlined
          dark
          clearable
          :label="$t('mediaDetail.appRef')"
          :hint="$t('mediaDetail.appRefHint')"
        />
      </div>

      <div class="col-12">
        <q-input
          v-model.trim="dockerImage"
          dense
          outlined
          dark
          clearable
          :label="$t('mediaDetail.dockerImage')"
          :hint="$t('mediaDetail.dockerImageOverrideHint')"
          :error="Boolean(validationError)"
          :error-message="validationError"
        />
      </div>

      <div class="col-12 flex justify-end">
        <q-btn
          color="primary"
          icon="mdi-content-save"
          :label="$t('common.save')"
          :loading="saving"
          :disable="Boolean(validationError) || !hasChanges"
          @click="save"
        />
      </div>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { MediaTypes, updateMediaItem } from 'src/composables/useUnifiedMedia'
import { listRuntimes } from 'src/services/gameRuntimesService'
import { logger } from 'src/utils/logger'

const props = defineProps({
  mediaItem: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['media-updated'])
const { t } = useI18n()
const $q = useQuasar()

const dockerImage = ref('')
const originalImage = ref('')
const runtime = ref(null)
const originalRuntime = ref(null)
const appRef = ref('')
const originalAppRef = ref('')
const saving = ref(false)

const runtimes = ref([])
const loadingRuntimes = ref(false)

const DOCKER_IMAGE_PATTERN = /^[A-Za-z0-9._/:@-]+$/

const isGame = computed(() => props.mediaItem?.media_type === MediaTypes.GAMES)
const normalizedImage = computed(() => normalizeDockerImage(dockerImage.value))
const validationError = computed(() => validateDockerImage(normalizedImage.value))

const runtimeOptions = computed(() =>
  runtimes.value.map((r) => ({
    label: r.is_builtin ? `${r.name} (${t('adminRuntimes.builtin')})` : r.name,
    value: r.name,
  })),
)

const runtimeLabel = computed(() => runtime.value || t('mediaDetail.defaultRuntime'))

const hasChanges = computed(
  () =>
    normalizedImage.value !== originalImage.value ||
    (runtime.value || '') !== (originalRuntime.value || '') ||
    appRef.value !== originalAppRef.value,
)

watch(
  () => props.mediaItem,
  (mediaItem) => {
    const lr = readLightrays(mediaItem)
    dockerImage.value = normalizeDockerImage(lr.docker_image)
    originalImage.value = dockerImage.value
    runtime.value = lr.profile || null
    originalRuntime.value = runtime.value
    appRef.value = String(lr.app_ref || '').trim()
    originalAppRef.value = appRef.value
  },
  { immediate: true },
)

onMounted(loadRuntimes)

async function loadRuntimes() {
  loadingRuntimes.value = true
  try {
    runtimes.value = await listRuntimes()
  } catch (error) {
    // Non-fatal: the select just shows no preset options (raw value kept).
    logger.warn('Could not load game runtimes:', error)
  } finally {
    loadingRuntimes.value = false
  }
}

function normalizeDockerImage(value) {
  return String(value || '').trim()
}

function parseExtraData(mediaItem) {
  const raw = mediaItem?.extra_data
  if (!raw) return {}
  if (typeof raw === 'object' && !Array.isArray(raw)) return { ...raw }
  if (typeof raw !== 'string') return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function readLightrays(mediaItem) {
  const extraData = parseExtraData(mediaItem)
  const lr = extraData.lightrays
  if (lr && typeof lr === 'object' && !Array.isArray(lr)) return lr
  // Legacy flat key.
  if (extraData.lightrays_docker_image) {
    return { docker_image: extraData.lightrays_docker_image }
  }
  return {}
}

function validateDockerImage(image) {
  if (!image) return ''
  const hasInvalidShape =
    image.length > 255 ||
    /^[-/:]/.test(image) ||
    image.endsWith('/') ||
    image.includes('//') ||
    image.includes('..') ||
    !DOCKER_IMAGE_PATTERN.test(image)
  return hasInvalidShape ? t('mediaDetail.invalidDockerImage') : ''
}

async function save() {
  const image = normalizedImage.value
  if (validateDockerImage(image)) return

  saving.value = true
  try {
    const extraData = parseExtraData(props.mediaItem)
    const existing =
      extraData.lightrays && typeof extraData.lightrays === 'object' && !Array.isArray(extraData.lightrays)
        ? { ...extraData.lightrays }
        : {}

    setOrDelete(existing, 'docker_image', image)
    setOrDelete(existing, 'profile', runtime.value || '')
    setOrDelete(existing, 'app_ref', appRef.value)

    if (Object.keys(existing).length > 0) {
      extraData.lightrays = existing
    } else {
      delete extraData.lightrays
    }
    delete extraData.lightrays_docker_image

    const updated = await updateMediaItem(props.mediaItem.guid, {
      extra_data: Object.keys(extraData).length > 0 ? extraData : null,
    })
    originalImage.value = image
    originalRuntime.value = runtime.value
    originalAppRef.value = appRef.value
    $q.notify({ type: 'positive', message: t('mediaDetail.streamingSettingsSaved') })
    emit('media-updated', updated)
  } catch {
    $q.notify({ type: 'negative', message: t('mediaDetail.streamingSettingsSaveFailed') })
  } finally {
    saving.value = false
  }
}

function setOrDelete(obj, key, value) {
  const v = String(value || '').trim()
  if (v) obj[key] = v
  else delete obj[key]
}
</script>

<style scoped>
.game-streaming-settings {
  background: rgba(18, 24, 34, 0.72);
  border-color: rgba(255, 255, 255, 0.12);
}
</style>
