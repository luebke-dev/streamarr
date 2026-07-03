<template>
  <!-- Loading / Preparing / Downloading state with backdrop hero. -->
  <div v-if="loading || status === 'downloading'" class="play-status play-status--prepare">
    <!-- Full-bleed backdrop sits underneath everything else; gracefully drops
         to a solid colour when the item has no backdrop. -->
    <div
      v-if="backdropUrl"
      class="play-status__backdrop"
      :style="{ backgroundImage: `url(${backdropUrl})` }"
    />
    <div class="play-status__scrim" />

    <div class="play-status__content">
      <div class="play-status__hero">
        <div v-if="posterUrl" class="play-status__poster-wrap">
          <q-img :src="posterUrl" class="play-status__poster" no-spinner />
          <div class="play-status__poster-glow" :style="{ backgroundImage: `url(${posterUrl})` }" />
        </div>

        <div class="play-status__meta">
          <div v-if="episodeBadge" class="play-status__badge">{{ episodeBadge }}</div>
          <h1 class="play-status__title">{{ titleLine }}</h1>
          <div v-if="subtitleLine" class="play-status__subtitle">{{ subtitleLine }}</div>
          <p v-if="descriptionLine" class="play-status__description">{{ descriptionLine }}</p>
        </div>
      </div>

      <div class="play-status__progress">
        <template v-if="isImporting">
          <q-spinner-gears size="40px" color="primary" />
          <div class="play-status__step">{{ downloadStepLabel }}</div>
        </template>
        <template v-else-if="downloadProgress > 0">
          <div class="play-status__bar">
            <q-linear-progress
              :value="downloadProgress / 100"
              size="6px"
              color="primary"
              track-color="grey-9"
              rounded
            />
          </div>
          <div class="play-status__step">
            {{ Math.round(downloadProgress) }}% ·
            {{ downloadStepLabel }}
          </div>
        </template>
        <template v-else>
          <q-spinner-dots size="44px" color="primary" />
          <div class="play-status__step">{{ downloadStepLabel }}</div>
        </template>
      </div>

      <q-btn
        flat
        dense
        no-caps
        color="grey-5"
        icon="mdi-arrow-left"
        :label="$t('playPage.cancel')"
        class="play-status__cancel"
        @click="$emit('back')"
      />
    </div>
  </div>

  <!-- Error state -->
  <div v-else-if="status === 'error'" class="play-status play-status--message">
    <div class="play-status__panel">
      <q-icon name="mdi-alert-circle" size="72px" color="negative" />
      <h2 class="play-status__title">{{ $t('playPage.error') }}</h2>
      <p class="play-status__description">{{ errorMessage }}</p>
      <div class="q-gutter-sm">
        <q-btn color="primary" :label="$t('playPage.retry')" @click="$emit('retry')" />
        <q-btn color="grey-7" outline :label="$t('playPage.goBack')" @click="$emit('back')" />
      </div>
    </div>
  </div>

  <!-- No release state -->
  <div v-else-if="status === 'no-release'" class="play-status play-status--message">
    <div class="play-status__panel">
      <q-icon name="mdi-magnify-close" size="72px" color="warning" />
      <h2 class="play-status__title">{{ $t('playPage.noRelease') }}</h2>
      <p class="play-status__description">{{ $t('playPage.noReleaseDesc') }}</p>
      <div class="q-gutter-sm">
        <q-btn
          color="primary"
          :label="$t('playPage.searchReleases')"
          @click="$emit('search-releases')"
        />
        <q-btn color="grey-7" outline :label="$t('playPage.goBack')" @click="$emit('back')" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getTmdbBackdropUrl,
  getTmdbPosterUrl,
  getTmdbStillUrl,
} from 'src/composables/useMediaFormatters'

const props = defineProps({
  loading: { type: Boolean, default: false },
  status: { type: String, default: '' },
  contentInfo: { type: Object, default: null },
  contentType: { type: String, default: '' },
  downloadProgress: { type: Number, default: 0 },
  downloadStatus: { type: String, default: '' },
  downloadPhase: { type: String, default: '' },
  errorMessage: { type: String, default: '' },
})

defineEmits(['back', 'retry', 'search-releases'])

const { t } = useI18n()

// Backdrop pulls from the item itself when available; for episodes we walk
// the optional show context too so we always fall back to a wide image rather
// than a portrait poster stretched across the screen.
const backdropUrl = computed(() => {
  const c = props.contentInfo
  if (!c) return null
  return (
    getTmdbBackdropUrl(c.backdrop_path, 'original') ||
    getTmdbBackdropUrl(c.show_backdrop_path, 'original') ||
    getTmdbStillUrl(c.still_path, 'w780') ||
    null
  )
})

const posterUrl = computed(() => {
  const c = props.contentInfo
  if (!c) return null
  return (
    getTmdbStillUrl(c.still_path, 'w500') ||
    getTmdbPosterUrl(c.poster_path, 'w500') ||
    getTmdbPosterUrl(c.show_poster_path, 'w500') ||
    null
  )
})

const isEpisode = computed(() => props.contentType === 'episode')

const titleLine = computed(() => {
  const c = props.contentInfo
  if (!c) return ''
  if (isEpisode.value) return c.show_title || c.title || c.name || ''
  return c.title || c.name || ''
})

const subtitleLine = computed(() => {
  const c = props.contentInfo
  if (!c || !isEpisode.value) return ''
  return c.title || ''
})

const episodeBadge = computed(() => {
  const c = props.contentInfo
  if (!c || !isEpisode.value) return ''
  const s = c.season_number
  const e = c.episode_number
  if (!s && !e) return ''
  return `S${String(s || 0).padStart(2, '0')}E${String(e || 0).padStart(2, '0')}`
})

const descriptionLine = computed(() => {
  const c = props.contentInfo
  if (!c) return ''
  return c.description || c.overview || ''
})

const normalizedDownloadStatus = computed(() =>
  String(props.downloadStatus || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_'),
)

const normalizedDownloadPhase = computed(() =>
  String(props.downloadPhase || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_'),
)

const downloadStepLabel = computed(() => {
  const step = normalizedDownloadPhase.value || normalizedDownloadStatus.value

  if (step === 'retrying_release' || step === 'retrying' || step === 'failed') {
    return t('playPage.downloadStatusRetryingRelease')
  }
  if (step === 'searching') {
    return t('playPage.downloadStatusSearching')
  }
  if (step === 'queued' || step === 'pending') {
    return t('playPage.downloadStatusQueued')
  }
  if (step === 'downloading') {
    return t('playPage.downloadStatusDownloading')
  }
  if (step === 'completed' || step === 'importing') {
    return t('playPage.downloadStatusImporting')
  }
  if (step === 'preparing') {
    return t('playPage.downloadStatusPreparing')
  }

  return t('playPage.preparingStream')
})

const isImporting = computed(
  () =>
    props.downloadProgress >= 100 ||
    normalizedDownloadPhase.value === 'importing' ||
    normalizedDownloadStatus.value === 'completed' ||
    normalizedDownloadStatus.value === 'importing',
)
</script>

<style scoped>
.play-status {
  position: relative;
  min-height: 100vh;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #050507;
  overflow: hidden;
  color: #fff;
}

.play-status__backdrop {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  filter: blur(18px) saturate(1.05);
  transform: scale(1.1);
  opacity: 0.55;
  z-index: 0;
}

.play-status__scrim {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 50% 25%, rgba(0, 0, 0, 0.25), rgba(0, 0, 0, 0.85) 70%),
    linear-gradient(180deg, rgba(5, 5, 7, 0.4) 0%, rgba(5, 5, 7, 0.95) 100%);
  z-index: 1;
}

.play-status__content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2.5rem;
  padding: 3rem 1.5rem 4rem;
  max-width: 720px;
  width: 100%;
}

.play-status__hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.75rem;
  text-align: center;
}

.play-status__poster-wrap {
  position: relative;
  width: 220px;
  aspect-ratio: 2 / 3;
}

.play-status__poster {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  border-radius: 14px;
  box-shadow: 0 24px 60px -12px rgba(0, 0, 0, 0.85);
}

/* Soft ambient glow behind the poster: same image, blurred and pushed out
   slightly. Plex/Apple TV use the same trick to make the card feel
   suspended in air. */
.play-status__poster-glow {
  position: absolute;
  inset: -20px;
  background-size: cover;
  background-position: center;
  filter: blur(32px) saturate(1.4);
  opacity: 0.6;
  z-index: 0;
  border-radius: 22px;
}

.play-status__meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  max-width: 540px;
}

.play-status__badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  font-size: 0.7rem;
  letter-spacing: 0.12em;
  font-weight: 600;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(10px);
  color: #ddd;
  text-transform: uppercase;
  margin-bottom: 0.4rem;
}

.play-status__title {
  font-size: clamp(1.5rem, 3vw, 2.4rem);
  line-height: 1.1;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.01em;
}

.play-status__subtitle {
  font-size: 1.05rem;
  color: #c4c4c4;
  font-weight: 500;
}

.play-status__description {
  margin: 0.8rem 0 0;
  font-size: 0.95rem;
  line-height: 1.5;
  color: #9d9d9d;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.play-status__progress {
  width: 100%;
  max-width: 380px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.8rem;
}

.play-status__bar {
  width: 100%;
}

.play-status__step {
  font-size: 0.85rem;
  color: #b9b9b9;
  letter-spacing: 0.02em;
  /* Subtle breathing animation so the screen doesn't feel frozen during
     long preparation windows. */
  animation: play-status-pulse 2.4s ease-in-out infinite;
}

@keyframes play-status-pulse {
  0%,
  100% {
    opacity: 0.7;
  }
  50% {
    opacity: 1;
  }
}

.play-status__cancel {
  margin-top: 0.5rem;
  letter-spacing: 0.04em;
}

/* Message states (error / no-release) ------------------------------- */

.play-status--message {
  background: #050507;
}

.play-status__panel {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  text-align: center;
  padding: 2rem 1.5rem;
  max-width: 480px;
}

.play-status--message .play-status__title {
  font-size: 1.6rem;
}

.play-status--message .play-status__description {
  color: #b6b6b6;
  margin: 0 0 1.5rem;
}

@media (max-width: 600px) {
  .play-status__poster-wrap {
    width: 170px;
  }
}
</style>
