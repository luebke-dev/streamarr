<template>
  <q-dialog v-model="show" position="right" full-height>
    <q-card class="stream-info-card" dark>
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">{{ $t('player.streamInfo') }}</div>
        <q-space />
        <q-btn icon="mdi-close" flat round dense v-close-popup />
      </q-card-section>

      <q-card-section class="q-pt-none">
        <!-- Source File Info -->
        <div class="info-section q-mb-md">
          <div class="text-subtitle2 text-primary q-mb-sm">{{ $t('player.sourceFile') }}</div>
          <div v-if="streamInfo?.source_file" class="info-grid">
            <div class="info-label">{{ $t('player.file') }}:</div>
            <div class="info-value text-caption">{{ streamInfo.source_file.file_name }}</div>

            <div class="info-label">{{ $t('player.size') }}:</div>
            <div class="info-value">{{ formatFileSize(streamInfo.source_file.file_size) }}</div>

            <div class="info-label">{{ $t('player.videoCodec') }}:</div>
            <div class="info-value">
              <q-chip dense size="sm" color="blue-grey-8">
                {{ streamInfo.source_file.video_codec }}
              </q-chip>
            </div>

            <div class="info-label">{{ $t('player.audioCodec') }}:</div>
            <div class="info-value">
              <q-chip dense size="sm" color="blue-grey-8">
                {{ streamInfo.source_file.audio_codec }}
              </q-chip>
            </div>

            <div class="info-label">{{ $t('player.resolution') }}:</div>
            <div class="info-value">
              {{ streamInfo.source_file.width }}x{{ streamInfo.source_file.height }}
            </div>

            <div class="info-label">{{ $t('player.bitDepth') }}:</div>
            <div class="info-value">
              <q-chip
                dense
                size="sm"
                :color="streamInfo.source_file.bit_depth > 8 ? 'orange-8' : 'green-8'"
              >
                {{ streamInfo.source_file.bit_depth }}-bit
              </q-chip>
            </div>

            <div class="info-label">{{ $t('player.duration') }}:</div>
            <div class="info-value">{{ formatDuration(streamInfo.source_file.duration) }}</div>
          </div>
          <div v-else class="text-grey-6">{{ $t('player.noSourceFileInfo') }}</div>
        </div>

        <q-separator dark class="q-my-md" />

        <!-- Transcoding Info -->
        <div class="info-section q-mb-md">
          <div class="text-subtitle2 text-primary q-mb-sm">{{ $t('player.transcoding') }}</div>
          <div v-if="streamInfo?.transcoding" class="info-grid">
            <div class="info-label">{{ $t('player.videoCodec') }}:</div>
            <div class="info-value">
              <q-chip dense size="sm" color="teal-8">
                {{ streamInfo.transcoding.video_codec }}
              </q-chip>
              <q-icon
                v-if="streamInfo.transcoding.video_codec === 'copy'"
                name="mdi-check-circle"
                color="positive"
                size="16px"
                class="q-ml-xs"
              >
                <q-tooltip>{{ $t('player.directStream') }}</q-tooltip>
              </q-icon>
            </div>

            <div class="info-label">{{ $t('player.audioCodec') }}:</div>
            <div class="info-value">
              <q-chip dense size="sm" color="teal-8">
                {{ streamInfo.transcoding.audio_codec }}
              </q-chip>
              <q-icon
                v-if="streamInfo.transcoding.audio_codec === 'copy'"
                name="mdi-check-circle"
                color="positive"
                size="16px"
                class="q-ml-xs"
              >
                <q-tooltip>{{ $t('player.directStream') }}</q-tooltip>
              </q-icon>
            </div>

            <div class="info-label">{{ $t('player.resolution') }}:</div>
            <div class="info-value">
              {{ streamInfo.transcoding.resolution || $t('player.original') }}
            </div>

            <div class="info-label">{{ $t('player.hardware') }}:</div>
            <div class="info-value">
              <q-chip
                dense
                size="sm"
                :color="streamInfo.transcoding.hw_accel ? 'green-8' : 'grey-8'"
              >
                {{ streamInfo.transcoding.hw_accel || $t('player.software') }}
              </q-chip>
            </div>
          </div>
          <div v-else class="text-grey-6">{{ $t('player.noTranscodingInfo') }}</div>
        </div>

        <q-separator dark class="q-my-md" />

        <!-- Transcoding Reasons -->
        <div class="info-section q-mb-md">
          <div class="text-subtitle2 text-primary q-mb-sm">
            {{ $t('player.transcodingReasons') }}
          </div>
          <div v-if="streamInfo?.transcoding_reasons?.length > 0">
            <q-chip
              v-for="(reason, idx) in streamInfo.transcoding_reasons"
              :key="idx"
              dense
              size="sm"
              color="orange-8"
              class="q-mr-xs q-mb-xs"
            >
              {{ reason }}
            </q-chip>
          </div>
          <div v-else class="text-grey-6">
            <q-chip dense size="sm" color="green-8">{{
              $t('player.noTranscodingRequired')
            }}</q-chip>
          </div>
        </div>

        <q-separator dark class="q-my-md" />

        <!-- Client Codec Capabilities -->
        <div class="info-section">
          <div class="text-subtitle2 text-primary q-mb-sm">{{ $t('player.clientCodecs') }}</div>
          <div v-if="clientCodecCapabilities" class="info-grid">
            <div class="info-label">{{ $t('player.video') }}:</div>
            <div class="info-value">
              <q-chip
                v-for="codec in clientCodecCapabilities.video_codecs"
                :key="codec"
                dense
                size="sm"
                color="blue-8"
                class="q-mr-xs"
              >
                {{ codec }}
              </q-chip>
            </div>

            <div class="info-label">{{ $t('player.audio') }}:</div>
            <div class="info-value">
              <q-chip
                v-for="codec in clientCodecCapabilities.audio_codecs"
                :key="codec"
                dense
                size="sm"
                color="purple-8"
                class="q-mr-xs"
              >
                {{ codec }}
              </q-chip>
            </div>

            <div class="info-label">{{ $t('player.resolution') }}:</div>
            <div class="info-value">
              <q-chip dense size="sm" color="cyan-8">
                {{ clientCodecCapabilities.max_resolution || $t('common.unknown') }}
              </q-chip>
            </div>

            <div class="info-label">HDR:</div>
            <div class="info-value">
              <q-chip
                dense
                size="sm"
                :color="clientCodecCapabilities.hdr_supported ? 'green-8' : 'grey-8'"
              >
                {{
                  clientCodecCapabilities.hdr_supported
                    ? $t('common.supported')
                    : $t('common.notSupported')
                }}
              </q-chip>
            </div>
          </div>
          <div v-else class="text-grey-6">{{ $t('player.loadingClientCodecs') }}</div>
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { formatDuration, formatFileSize } from 'src/composables/useMediaFormatters'
import { getCodecCapabilities } from 'src/composables/usePlay'
import { logger } from 'src/utils/logger'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  streamInfo: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue'])

const show = ref(props.modelValue)
const clientCodecCapabilities = ref(null)

watch(
  () => props.modelValue,
  async (val) => {
    show.value = val
    if (val && !clientCodecCapabilities.value) {
      try {
        clientCodecCapabilities.value = await getCodecCapabilities()
      } catch (e) {
        logger.error('Failed to get codec capabilities:', e)
      }
    }
  },
)

watch(show, (val) => emit('update:modelValue', val))
</script>

<style lang="scss" scoped>
.stream-info-card {
  width: 400px;
  max-width: 100vw;
  background: rgba(30, 30, 30, 0.98);

  .info-section {
    .info-grid {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 8px 12px;
      align-items: center;

      .info-label {
        color: rgba(255, 255, 255, 0.6);
        font-size: 12px;
      }

      .info-value {
        color: white;
        font-size: 13px;
        word-break: break-word;
      }
    }
  }
}
</style>
