<template>
  <q-card v-if="isGame" flat bordered class="q-mt-xl game-streaming-settings">
    <q-card-section class="row items-center justify-between q-gutter-sm">
      <div class="text-h6 text-white">{{ $t('mediaDetail.gameStreaming') }}</div>
      <q-chip dense color="blue-grey-8" text-color="white">
        {{ imageLabel }}
      </q-chip>
    </q-card-section>

    <q-card-section class="row q-col-gutter-md items-start">
      <div class="col-12 col-md-9">
        <q-input
          v-model.trim="dockerImage"
          dense
          outlined
          dark
          clearable
          :label="$t('mediaDetail.dockerImage')"
          :hint="$t('mediaDetail.defaultSteamImage')"
          :error="Boolean(validationError)"
          :error-message="validationError"
        />
      </div>
      <div class="col-12 col-md-3">
        <q-btn
          color="primary"
          icon="mdi-content-save"
          class="full-width"
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
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { MediaTypes, updateMediaItem } from 'src/composables/useUnifiedMedia'

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
const saving = ref(false)

const DOCKER_IMAGE_PATTERN = /^[A-Za-z0-9._/:@-]+$/

const isGame = computed(() => props.mediaItem?.media_type === MediaTypes.GAMES)
const normalizedImage = computed(() => normalizeDockerImage(dockerImage.value))
const imageLabel = computed(() => normalizedImage.value || t('mediaDetail.defaultSteam'))
const validationError = computed(() => validateDockerImage(normalizedImage.value))
const hasChanges = computed(() => normalizedImage.value !== originalImage.value)

watch(
  () => props.mediaItem,
  (mediaItem) => {
    const image = readDockerImage(mediaItem)
    dockerImage.value = image
    originalImage.value = image
  },
  { immediate: true },
)

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

function readDockerImage(mediaItem) {
  const extraData = parseExtraData(mediaItem)
  const lightraysData = extraData.lightrays
  if (lightraysData && typeof lightraysData === 'object' && !Array.isArray(lightraysData)) {
    return normalizeDockerImage(lightraysData.docker_image)
  }
  return normalizeDockerImage(extraData.lightrays_docker_image)
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
  const error = validateDockerImage(image)
  if (error) return

  saving.value = true
  try {
    const extraData = parseExtraData(props.mediaItem)
    const hasLightraysObject =
      extraData.lightrays &&
      typeof extraData.lightrays === 'object' &&
      !Array.isArray(extraData.lightrays)
    const lightraysData = hasLightraysObject ? { ...extraData.lightrays } : {}

    if (image) {
      lightraysData.docker_image = image
      extraData.lightrays = lightraysData
    } else {
      delete lightraysData.docker_image
      if (Object.keys(lightraysData).length > 0) {
        extraData.lightrays = lightraysData
      } else {
        delete extraData.lightrays
      }
    }
    delete extraData.lightrays_docker_image

    const updated = await updateMediaItem(props.mediaItem.guid, {
      extra_data: Object.keys(extraData).length > 0 ? JSON.stringify(extraData) : null,
    })
    originalImage.value = image
    $q.notify({ type: 'positive', message: t('mediaDetail.streamingSettingsSaved') })
    emit('media-updated', updated)
  } catch {
    $q.notify({ type: 'negative', message: t('mediaDetail.streamingSettingsSaveFailed') })
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.game-streaming-settings {
  background: rgba(18, 24, 34, 0.72);
  border-color: rgba(255, 255, 255, 0.12);
}
</style>
