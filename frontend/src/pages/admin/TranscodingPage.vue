<template>
  <q-page class="transcoding-page q-pa-md">
    <div class="row items-center q-mb-lg">
      <div class="col">
        <div class="row items-center q-gutter-sm">
          <h4 class="text-h4 text-white q-ma-none">{{ $t('transcodingPage.title') }}</h4>
          <q-chip
            v-if="computingProvider"
            :icon="computingProvider === 'kubernetes' ? 'mdi-kubernetes' : 'mdi-docker'"
            color="primary"
            text-color="white"
            size="sm"
          >
            {{ computingProvider === 'kubernetes' ? 'Kubernetes' : 'Docker' }}
          </q-chip>
        </div>
        <p class="text-grey-4 q-ma-none q-mt-xs">{{ $t('transcodingPage.subtitle') }}</p>
      </div>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="loading" class="q-gutter-md">
      <q-card class="settings-card">
        <q-card-section>
          <q-skeleton type="rect" height="40px" class="q-mb-md" />
          <q-skeleton type="rect" height="56px" class="q-mb-md" />
          <q-skeleton type="rect" height="56px" class="q-mb-md" />
          <q-skeleton type="rect" height="56px" />
        </q-card-section>
      </q-card>
    </div>

    <q-form v-else @submit.prevent="saveSettings">
      <!-- General Settings -->
      <q-card class="settings-card q-mb-md">
        <q-card-section>
          <div class="text-h6 text-white q-mb-md">
            <q-icon name="mdi-cog" class="q-mr-sm" />
            {{ $t('transcodingPage.generalSection') }}
          </div>

          <!-- Enable Transcoding -->
          <div class="q-mb-md">
            <q-toggle
              v-model="settings.enabled"
              :label="$t('transcodingPage.enableTranscoding')"
              color="primary"
              :disable="saving"
            />
            <p class="text-grey-6 text-caption q-mt-xs q-mb-none">
              {{ $t('transcodingPage.enableTranscodingHint') }}
            </p>
          </div>

          <q-separator class="q-my-md" />

          <!-- FFmpeg Docker Image -->
          <div class="q-mb-md">
            <q-input
              v-model="settings.ffmpeg_image"
              :label="$t('transcodingPage.ffmpegImage')"
              outlined
              :hint="$t('transcodingPage.ffmpegImageHint')"
              :disable="saving || !settings.enabled"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-docker" />
              </template>
            </q-input>
          </div>

          <!-- Temp Path -->
          <div>
            <q-input
              v-model="settings.temp_path"
              :label="$t('transcodingPage.tempPath')"
              outlined
              :hint="$t('transcodingPage.tempPathHint')"
              :disable="saving || !settings.enabled"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-folder-cog" />
              </template>
            </q-input>
          </div>
        </q-card-section>
      </q-card>

      <!-- Video Settings -->
      <q-card class="settings-card q-mb-md">
        <q-card-section>
          <div class="text-h6 text-white q-mb-md">
            <q-icon name="mdi-video" class="q-mr-sm" />
            {{ $t('transcodingPage.videoSection') }}
          </div>

          <!-- Allowed Video Codecs -->
          <div class="q-mb-md">
            <q-select
              v-model="settings.allowed_video_codecs"
              :options="videoCodecOptions"
              :label="$t('transcodingPage.allowedVideoCodecs')"
              outlined
              emit-value
              map-options
              multiple
              use-chips
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.allowedVideoCodecsHint') }}
            </p>
          </div>

          <!-- Max Resolution -->
          <div class="q-mb-md">
            <q-select
              v-model="settings.max_resolution"
              :options="resolutionOptions"
              :label="$t('transcodingPage.maxResolution')"
              outlined
              emit-value
              map-options
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.maxResolutionHint') }}
            </p>
          </div>

          <!-- Default Video Bitrate -->
          <div class="q-mb-md">
            <q-select
              v-model="settings.default_video_bitrate"
              :options="videoBitrateOptions"
              :label="$t('transcodingPage.defaultVideoBitrate')"
              outlined
              emit-value
              map-options
              clearable
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.defaultVideoBitrateHint') }}
            </p>
          </div>

          <!-- Default CRF -->
          <div>
            <div class="text-subtitle2 q-mb-xs">
              {{ $t('transcodingPage.defaultCrf') }}: {{ settings.default_crf }}
            </div>
            <q-slider
              v-model="settings.default_crf"
              :min="0"
              :max="51"
              :step="1"
              label
              :label-value="settings.default_crf"
              color="primary"
              :disable="saving || !settings.enabled || !!settings.default_video_bitrate"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.defaultCrfHint') }}
            </p>
          </div>
        </q-card-section>
      </q-card>

      <!-- Audio Settings -->
      <q-card class="settings-card q-mb-md">
        <q-card-section>
          <div class="text-h6 text-white q-mb-md">
            <q-icon name="mdi-music" class="q-mr-sm" />
            {{ $t('transcodingPage.audioSection') }}
          </div>

          <!-- Allowed Audio Codecs -->
          <div class="q-mb-md">
            <q-select
              v-model="settings.allowed_audio_codecs"
              :options="audioCodecOptions"
              :label="$t('transcodingPage.allowedAudioCodecs')"
              outlined
              emit-value
              map-options
              multiple
              use-chips
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.allowedAudioCodecsHint') }}
            </p>
          </div>

          <!-- Default Audio Bitrate -->
          <div>
            <q-select
              v-model="settings.default_audio_bitrate"
              :options="audioBitrateOptions"
              :label="$t('transcodingPage.defaultAudioBitrate')"
              outlined
              emit-value
              map-options
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.defaultAudioBitrateHint') }}
            </p>
          </div>
        </q-card-section>
      </q-card>

      <!-- Performance Settings -->
      <q-card class="settings-card q-mb-md">
        <q-card-section>
          <div class="text-h6 text-white q-mb-md">
            <q-icon name="mdi-speedometer" class="q-mr-sm" />
            {{ $t('transcodingPage.performanceSection') }}
          </div>

          <!-- Hardware Acceleration -->
          <div class="q-mb-md">
            <q-toggle
              v-model="settings.hardware_acceleration"
              :label="$t('transcodingPage.enableHardwareAcceleration')"
              color="primary"
              :disable="saving || !settings.enabled"
            />

            <q-slide-transition>
              <div v-if="settings.hardware_acceleration" class="q-mt-sm">
                <q-input
                  v-model="settings.hardware_acceleration_device"
                  :label="$t('transcodingPage.hardwareDevice')"
                  outlined
                  :hint="$t('transcodingPage.hardwareDeviceHint')"
                  :disable="saving"
                  clearable
                >
                  <template v-slot:prepend>
                    <q-icon name="mdi-chip" />
                  </template>
                </q-input>
              </div>
            </q-slide-transition>
          </div>

          <q-separator class="q-my-md" />

          <!-- Thread Count -->
          <div class="q-mb-md">
            <div class="text-subtitle2 q-mb-xs">
              {{ $t('transcodingPage.threadCount') }}:
              {{ settings.thread_count === 0 ? $t('transcodingPage.auto') : settings.thread_count }}
            </div>
            <q-slider
              v-model="settings.thread_count"
              :min="0"
              :max="32"
              :step="1"
              label
              :label-value="
                settings.thread_count === 0 ? $t('transcodingPage.auto') : settings.thread_count
              "
              color="primary"
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.threadCountHint') }}
            </p>
          </div>

          <q-separator class="q-my-md" />

          <!-- Prefer Compatible Codecs -->
          <div class="q-mb-md">
            <q-toggle
              v-model="settings.prefer_compatible_codecs"
              :label="$t('transcodingPage.preferCompatibleCodecs')"
              color="primary"
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs q-mb-none">
              {{ $t('transcodingPage.preferCompatibleCodecsHint') }}
            </p>
          </div>

          <q-separator class="q-my-md" />

          <!-- Trickplay cache budget -->
          <div class="q-mb-md">
            <q-input
              v-model.number="settings.trickplay_cache_max_gb"
              type="number"
              min="0"
              max="1000"
              step="0.5"
              :label="$t('transcodingPage.trickplayCacheMax')"
              :suffix="$t('transcodingPage.gigabytes')"
              outlined
              dense
              :disable="saving"
              style="max-width: 260px"
            />
            <p class="text-grey-6 text-caption q-mt-xs q-mb-none">
              {{ $t('transcodingPage.trickplayCacheMaxHint') }}
            </p>
          </div>

          <q-separator class="q-my-md" />

          <!-- HLS Segment Duration -->
          <div>
            <div class="text-subtitle2 q-mb-xs">
              {{ $t('transcodingPage.hlsSegmentDuration') }}: {{ settings.hls_segment_duration }}s
            </div>
            <q-slider
              v-model="settings.hls_segment_duration"
              :min="2"
              :max="15"
              :step="1"
              label
              :label-value="`${settings.hls_segment_duration}s`"
              color="primary"
              :disable="saving || !settings.enabled"
            />
            <p class="text-grey-6 text-caption q-mt-xs">
              {{ $t('transcodingPage.hlsSegmentDurationHint') }}
            </p>
          </div>
        </q-card-section>
      </q-card>

      <!-- Action Buttons -->
      <div class="row q-gutter-sm q-mt-md">
        <q-btn
          type="submit"
          color="primary"
          :label="$t('common.save')"
          :loading="saving"
          :disable="!hasChanges"
          icon="mdi-content-save"
        />
        <q-btn
          color="grey-7"
          :label="$t('common.reset')"
          @click="resetSettings"
          :disable="saving || !hasChanges"
          outline
          icon="mdi-refresh"
        />
      </div>
    </q-form>
  </q-page>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getTranscodingSettings,
  saveTranscodingSettings,
  getComputingStatus,
} from 'src/services/libraryAdminService'
import { logger } from 'src/utils/logger'
useI18n()

// State
const loading = ref(false)
const saving = ref(false)

const defaultSettings = {
  enabled: false,
  max_resolution: '1080p',
  hardware_acceleration: false,
  hardware_acceleration_device: null,
  ffmpeg_image: 'lscr.io/linuxserver/ffmpeg:latest',
  allowed_video_codecs: ['h264', 'h265', 'av1', 'vp9'],
  allowed_audio_codecs: ['aac', 'opus', 'mp3'],
  default_video_bitrate: null,
  default_audio_bitrate: '128k',
  default_crf: 23,
  hls_segment_duration: 6,
  thread_count: 0,
  temp_path: '/temp',
  prefer_compatible_codecs: false,
  trickplay_cache_max_gb: 5,
}

const settings = reactive({ ...defaultSettings })
const computingProvider = ref(null)
const originalSettings = reactive({ ...defaultSettings })

// Options
const resolutionOptions = [
  { label: '480p (SD)', value: '480p' },
  { label: '720p (HD)', value: '720p' },
  { label: '1080p (Full HD)', value: '1080p' },
  { label: '1440p (2K)', value: '1440p' },
  { label: '2160p (4K)', value: '2160p' },
]

const videoCodecOptions = [
  { label: 'H.264 / AVC', value: 'h264' },
  { label: 'H.265 / HEVC', value: 'h265' },
  { label: 'AV1', value: 'av1' },
  { label: 'VP9', value: 'vp9' },
]

const audioCodecOptions = [
  { label: 'AAC', value: 'aac' },
  { label: 'Opus', value: 'opus' },
  { label: 'MP3', value: 'mp3' },
]

const videoBitrateOptions = [
  { label: '1.000 kbps (480p)', value: '1000k' },
  { label: '2.500 kbps (720p)', value: '2500k' },
  { label: '5.000 kbps (1080p)', value: '5000k' },
  { label: '8.000 kbps (1080p HQ)', value: '8000k' },
  { label: '12.000 kbps (1440p)', value: '12000k' },
  { label: '20.000 kbps (4K)', value: '20000k' },
]

const audioBitrateOptions = [
  { label: '96 kbps', value: '96k' },
  { label: '128 kbps', value: '128k' },
  { label: '192 kbps', value: '192k' },
  { label: '256 kbps', value: '256k' },
  { label: '320 kbps', value: '320k' },
]

// Computed
const hasChanges = computed(() => {
  return Object.keys(defaultSettings).some((key) => {
    return settings[key] !== originalSettings[key]
  })
})

// Methods
const applyData = (data, target) => {
  Object.keys(defaultSettings).forEach((key) => {
    target[key] = data[key] !== undefined ? data[key] : defaultSettings[key]
  })
}

const loadSettings = async () => {
  loading.value = true
  try {
    const data = await getTranscodingSettings()
    applyData(data, settings)
    applyData(data, originalSettings)
  } catch (error) {
    logger.error('Failed to load transcoding settings:', error)
  } finally {
    loading.value = false
  }
}

const saveSettings = async () => {
  saving.value = true
  try {
    const payload = {}
    Object.keys(defaultSettings).forEach((key) => {
      payload[key] = settings[key]
    })

    const data = await saveTranscodingSettings(payload)
    applyData(data, originalSettings)
  } catch (error) {
    logger.error('Failed to save transcoding settings:', error)
  } finally {
    saving.value = false
  }
}

const resetSettings = () => {
  applyData(originalSettings, settings)
}

const loadComputingStatus = async () => {
  try {
    const data = await getComputingStatus()
    computingProvider.value = data.provider
  } catch (error) {
    logger.error('Failed to load computing status:', error)
  }
}

// Lifecycle
onMounted(() => {
  loadSettings()
  loadComputingStatus()
})
</script>

<style lang="scss" scoped>
.transcoding-page {
  max-width: 800px;
  margin: 0 auto;
}

.settings-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
