<template>
  <div
    class="custom-controls-overlay"
    :class="{ 'controls-visible': controlsVisible, 'controls-hidden': !controlsVisible }"
    @mousemove="showControls"
    @mouseleave="scheduleHideControls"
    @touchstart="showControls"
    @click="handleOverlayClick"
    @wheel.prevent="handleWheel"
  >
    <!-- Loading Spinner (during seek) -->
    <div v-if="isSeeking" class="seek-loading">
      <q-spinner-dots size="60px" color="white" />
      <div class="text-white q-mt-md">{{ $t('player.seeking') }}</div>
    </div>

    <!-- Center Play/Pause Button (click to toggle) -->
    <div class="center-controls" @click.stop="togglePlayPause">
      <transition name="fade">
        <q-icon
          v-if="showCenterIcon"
          :name="isPlaying ? 'mdi-pause' : 'mdi-play'"
          size="80px"
          color="white"
          class="center-play-icon"
        />
      </transition>
    </div>

    <!-- Bottom Controls Bar -->
    <div class="bottom-controls" @click.stop>
      <!-- Progress Bar with Time Display -->
      <div class="progress-row">
        <div
          class="progress-container"
          @click="handleProgressClick"
          @touchstart.prevent="handleProgressTouch"
          ref="progressBar"
        >
          <div class="progress-bar-bg">
            <div class="progress-bar-buffered" :style="{ width: bufferedPercent + '%' }"></div>
            <div class="progress-bar-played" :style="{ width: progressPercent + '%' }"></div>
            <div
              class="progress-bar-handle"
              :style="{ left: progressPercent + '%' }"
              @mousedown="startDragging"
              @touchstart.prevent="startDragging"
            ></div>
          </div>
          <!-- Preview tooltip -->
          <div
            v-if="hoverTime !== null"
            class="progress-preview"
            :style="{ left: hoverPercent + '%' }"
          >
            {{ formatTime(hoverTime) }}
          </div>
        </div>
        <!-- Time Display next to progress bar -->
        <div class="time-display q-ml-md">
          <span class="current-time">{{ formatTime(realCurrentTime) }}</span>
          <span class="time-separator"> / </span>
          <span class="total-time">{{ formatTime(totalDuration) }}</span>
        </div>
      </div>

      <!-- Controls Row -->
      <div class="controls-row">
        <!-- Left: Play/Pause, Skip buttons -->
        <div class="controls-left">
          <q-btn flat round dense color="white" @click="togglePlayPause">
            <q-icon :name="isPlaying ? 'mdi-pause' : 'mdi-play'" :size="iconSizeLg" />
          </q-btn>
          <!-- Previous Episode (for shows) -->
          <q-btn
            v-if="showEpisodeControls"
            flat
            round
            dense
            color="white"
            @click="$emit('previous-episode')"
            :disable="!hasPreviousEpisode"
          >
            <q-icon name="mdi-skip-previous" :size="iconSize" />
            <EpisodeNavTooltip
              :episode="previousEpisodeData"
              :fallback-label="$t('player.previousEpisode')"
            />
          </q-btn>
          <!-- Skip backward 10s -->
          <q-btn flat round dense color="white" @click="skipBackward" class="q-ml-sm">
            <q-icon name="mdi-rewind-10" :size="iconSize" />
          </q-btn>

          <!-- Skip forward 10s -->
          <q-btn flat round dense color="white" @click="skipForward" class="q-ml-sm">
            <q-icon name="mdi-fast-forward-10" :size="iconSize" />
          </q-btn>
          <!-- Next Episode (for shows) -->
          <q-btn
            v-if="showEpisodeControls"
            flat
            round
            dense
            color="white"
            @click="$emit('next-episode')"
            :disable="!hasNextEpisode"
          >
            <q-icon name="mdi-skip-next" :size="iconSize" />
            <EpisodeNavTooltip
              :episode="nextEpisodeData"
              :fallback-label="$t('player.nextEpisode')"
            />
          </q-btn>
          <!-- Volume (hidden on mobile - uses hardware volume) -->
          <div v-if="!isMobile" class="volume-control q-ml-md">
            <q-btn flat round dense color="white" @click="toggleMute">
              <q-icon :name="volumeIcon" :size="iconSize" />
            </q-btn>
            <q-slider
              v-model="volumeLevel"
              :min="0"
              :max="1"
              :step="0.01"
              color="white"
              class="volume-slider"
              @update:model-value="onVolumeChange"
            />
          </div>
        </div>

        <!-- Right: Settings, Fullscreen -->
        <div class="controls-right">
          <!-- Secondary actions: shown inline on desktop, in overflow menu on mobile -->
          <PlayerSecondaryActions
            :is-mobile="isMobile"
            :is-favorited="isFavorited"
            :identifying-loading="identifyingLoading"
            :is-superuser="authStore.isSuperuser"
            :icon-size="iconSize"
            @toggle-favorite="$emit('toggle-favorite')"
            @identify-song="$emit('identify-song')"
            @report-problem="$emit('report-problem')"
            @show-info="showInfoDialog = true"
          />

          <!-- Audio Track Selection (always visible) -->
          <q-btn flat round dense color="white">
            <q-icon name="mdi-account-voice" :size="iconSize" />
            <PlayerPickerMenu
              :header="$t('player.audioTrack')"
              :items="audioTracks"
              :model-value="currentAudioTrack"
              :empty-label="$t('player.noAudioTracks')"
              default-item-prefix="Track"
              @select="selectAudioTrack"
            />
          </q-btn>

          <!-- Subtitle Selection (always visible) -->
          <q-btn flat round dense color="white">
            <q-icon name="mdi-subtitles" :size="iconSize" />
            <PlayerPickerMenu
              :header="$t('player.subtitles')"
              :items="subtitleTracks"
              :model-value="currentSubtitle"
              :empty-label="$t('player.noSubtitles')"
              default-item-prefix="Subtitle"
              :has-null-option="true"
              :null-option-label="$t('player.subtitlesOff')"
              @select="selectSubtitle"
            />
          </q-btn>

          <!-- Quality Selection (always visible) -->
          <q-btn flat round dense color="white">
            <q-icon name="mdi-cog" :size="iconSize" />
            <PlayerPickerMenu
              :header="$t('player.quality')"
              :items="qualityLevels"
              :model-value="currentQuality"
              :empty-label="$t('player.autoQuality')"
              :item-disabled="(level) => !level.is_available"
              @select="selectQuality"
            >
              <template #item="{ item: level }">
                <q-item-label>
                  {{ level.label || `${level.height}p` }}
                  <q-badge v-if="level.source === 'release'" color="grey" class="q-ml-sm">
                    {{ $t('player.downloadRequired') }}
                  </q-badge>
                  <q-badge v-else-if="level.source === 'transcode'" color="info" class="q-ml-sm">
                    {{ $t('player.transcode') }}
                  </q-badge>
                  <q-badge
                    v-else-if="level.is_downloaded && !level.is_current"
                    color="positive"
                    class="q-ml-sm"
                  >
                    {{ $t('player.downloaded') }}
                  </q-badge>
                </q-item-label>
              </template>
            </PlayerPickerMenu>
          </q-btn>

          <!-- Picture-in-Picture (always visible) -->
          <q-btn
            v-if="pipSupported"
            flat
            round
            dense
            color="white"
            @click="togglePip"
            class="q-ml-sm"
          >
            <q-icon
              :name="
                isPip
                  ? 'mdi-picture-in-picture-bottom-right-outline'
                  : 'mdi-picture-in-picture-bottom-right'
              "
              :size="iconSize"
            />
            <q-tooltip>{{ isPip ? $t('player.exitPip') : $t('player.pip') }}</q-tooltip>
          </q-btn>

          <!-- Fullscreen (always visible) -->
          <q-btn flat round dense color="white" @click="toggleFullscreen" class="q-ml-sm">
            <q-icon
              :name="isFullscreen ? 'mdi-fullscreen-exit' : 'mdi-fullscreen'"
              :size="iconSize"
            />
          </q-btn>
        </div>
      </div>
    </div>

    <!-- Stream Info Dialog (Admin only) -->
    <StreamInfoDialog v-model="showInfoDialog" :stream-info="streamInfo" />

    <!-- Title Bar (Top) -->
    <div class="top-controls">
      <q-btn flat round dense color="white" @click="$emit('back')" class="back-button">
        <q-icon name="mdi-arrow-left" :size="iconSizeLg" />
      </q-btn>
      <div class="title-info">
        <div class="title-text">{{ title }}</div>
        <div v-if="subtitle" class="subtitle-text">{{ subtitle }}</div>
        <div class="subtitle-text">{{ $t('player.endsAt', { time: formatEndTime() }) }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from 'stores/auth'
import { formatTime } from 'src/composables/useMediaFormatters'
import { usePictureInPicture } from 'src/composables/usePictureInPicture'
import { useKeyboardShortcuts } from 'src/composables/useKeyboardShortcuts'
import { useControlsAutoHide } from 'src/composables/useControlsAutoHide'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'
import { useProgressBar } from 'src/composables/useProgressBar'
import { useMediaTracks } from 'src/composables/useMediaTracks'
import StreamInfoDialog from './StreamInfoDialog.vue'
import EpisodeNavTooltip from './EpisodeNavTooltip.vue'
import PlayerPickerMenu from './PlayerPickerMenu.vue'
import PlayerSecondaryActions from './PlayerSecondaryActions.vue'
import { logger } from 'src/utils/logger'

const $q = useQuasar()
const { locale } = useI18n()
const authStore = useAuthStore()

// Player tuning constants
const CONTROLS_HIDE_DELAY_MS = 3000
const CENTER_ICON_FLASH_MS = 300
const SKIP_SECONDS = 10
const VOLUME_WHEEL_STEP = 0.05
const VOLUME_KEYBOARD_STEP = 0.1
const DEFAULT_VOLUME = 0.6
const VOLUME_THRESHOLD_LOW = 0.3
const VOLUME_THRESHOLD_HIGH = 0.7

// Responsive helpers
const isMobile = computed(() => $q.screen.xs || $q.screen.sm)
const iconSize = computed(() => (isMobile.value ? '20px' : '24px'))
const iconSizeLg = computed(() => (isMobile.value ? '24px' : '28px'))

const props = defineProps({
  playerState: {
    type: Object,
    default: null,
  },
  mediaState: {
    type: Object,
    default: null,
  },
  navigationState: {
    type: Object,
    default: null,
  },
  streamState: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits([
  'seek', // Emit when user wants to seek to a position (triggers new transcode)
  'change-audio-track', // Emit when user selects a different audio track (triggers retranscode)
  'toggle-play',
  'toggle-mute',
  'volume-change',
  'toggle-fullscreen',
  'back',
  'next-episode',
  'previous-episode',
  'toggle-favorite',
  'select-quality',
  'identify-song',
  'report-problem',
])

const videoElement = computed(() => props.playerState?.videoElement ?? null)
const player = computed(() => props.playerState?.player ?? null)
const totalDuration = computed(() => props.playerState?.totalDuration ?? 0)
const transcodeStartPosition = computed(() => props.playerState?.transcodeStartPosition ?? 0)
const streamPosition = computed(() => props.playerState?.streamPosition ?? 0)
const bufferedAmount = computed(() => props.playerState?.bufferedAmount ?? 0)
const isSeeking = computed(() => props.playerState?.isSeeking ?? false)
const isPlaying = computed(() => props.playerState?.isPlaying ?? false)
const contentId = computed(() => props.mediaState?.contentId ?? '')
const contentType = computed(() => props.mediaState?.contentType ?? 'movie')
const title = computed(() => props.mediaState?.title ?? '')
const subtitle = computed(() => props.mediaState?.subtitle ?? '')
const isFavorited = computed(() => props.mediaState?.isFavorited ?? false)
const identifyingLoading = computed(() => props.mediaState?.identifyingLoading ?? false)
const showEpisodeControls = computed(() => props.navigationState?.showEpisodeControls ?? false)
const hasPreviousEpisode = computed(() => props.navigationState?.hasPreviousEpisode ?? false)
const hasNextEpisode = computed(() => props.navigationState?.hasNextEpisode ?? false)
const previousEpisodeData = computed(() => props.navigationState?.previousEpisodeData ?? null)
const nextEpisodeData = computed(() => props.navigationState?.nextEpisodeData ?? null)
const streamInfo = computed(() => props.streamState?.streamInfo ?? null)

// State
const showCenterIcon = ref(false)
const volumeLevel = ref(DEFAULT_VOLUME)
const isMuted = ref(false)
const isFullscreen = ref(false)
const isDragging = ref(false)
const showInfoDialog = ref(false)
const progressBar = ref(null)

// Auto-hide controls after inactivity (only while playing and not dragging)
const isPlayingRef = computed(() => isPlaying.value)
const { controlsVisible, showControls, scheduleHideControls } = useControlsAutoHide({
  delayMs: CONTROLS_HIDE_DELAY_MS,
  isPlayingRef,
  isDraggingRef: isDragging,
})

// Subtitle, audio track, and quality state — track lists + selected audio
// track come from the shared video-player store via useMediaTracks; the
// v-model (currentAudioTrack) is therefore coupled to the store state.
const {
  audioTracks,
  subtitleTracks,
  qualityLevels,
  currentAudioTrack,
  currentSubtitle,
  currentQuality,
  selectAudioTrack,
  selectSubtitle,
  selectQuality,
} = useMediaTracks({
  getContentId: () => contentId.value,
  getContentType: () => contentType.value,
  getPlayer: () => player.value,
  onChangeAudioTrack: (streamIndex) => emit('change-audio-track', streamIndex),
  onSelectQuality: (level) => emit('select-quality', level),
})

// Computed
const realCurrentTime = computed(() => {
  return transcodeStartPosition.value + streamPosition.value
})

const progressPercent = computed(() => {
  if (totalDuration.value <= 0) return 0
  return Math.min(100, (realCurrentTime.value / totalDuration.value) * 100)
})

const bufferedPercent = computed(() => {
  if (totalDuration.value <= 0) return 0
  const bufferedEnd = transcodeStartPosition.value + bufferedAmount.value
  return Math.min(100, (bufferedEnd / totalDuration.value) * 100)
})

const volumeIcon = computed(() => {
  if (isMuted.value || volumeLevel.value === 0) return 'mdi-volume-off'
  if (volumeLevel.value < VOLUME_THRESHOLD_LOW) return 'mdi-volume-low'
  if (volumeLevel.value < VOLUME_THRESHOLD_HIGH) return 'mdi-volume-medium'
  return 'mdi-volume-high'
})

// Methods
const formatEndTime = () => {
  const remainingSeconds = totalDuration.value - realCurrentTime.value
  if (!isFinite(remainingSeconds) || remainingSeconds < 0) return '--:--'

  const now = new Date()
  const endTime = new Date(now.getTime() + remainingSeconds * 1000)

  return endTime.toLocaleTimeString(locale.value, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

const handleOverlayClick = (e) => {
  // Only toggle play/pause if clicking on the overlay itself, not on controls
  if (e.target.classList.contains('custom-controls-overlay')) {
    togglePlayPause()
  }
}

const controlTimers = useTimeoutRegistry()
let centerIconTimer = null

const togglePlayPause = () => {
  showCenterIcon.value = true
  controlTimers.clear(centerIconTimer)
  centerIconTimer = controlTimers.schedule(() => {
    showCenterIcon.value = false
  }, CENTER_ICON_FLASH_MS)
  emit('toggle-play')
}

const toggleMute = () => {
  isMuted.value = !isMuted.value
  emit('toggle-mute', isMuted.value)
}

const onVolumeChange = (value) => {
  const newMuted = value === 0
  if (isMuted.value && !newMuted) {
    // User raised volume while muted — actually unmute the player too
    isMuted.value = false
    emit('toggle-mute', false)
  } else {
    isMuted.value = newMuted
  }
  emit('volume-change', value)
}

const toggleFullscreen = () => {
  isFullscreen.value = !isFullscreen.value
  emit('toggle-fullscreen')
}

// Picture-in-Picture
const { isPip, pipSupported, togglePip } = usePictureInPicture(videoElement)

// Stream Info Dialog (Admin) — opened via showInfoDialog ref
const skipForward = () => {
  const newPosition = Math.min(totalDuration.value, realCurrentTime.value + SKIP_SECONDS)
  emit('seek', newPosition)
}

const skipBackward = () => {
  const newPosition = Math.max(0, realCurrentTime.value - SKIP_SECONDS)
  emit('seek', newPosition)
}

// Progress bar interaction (click/drag/touch/hover)
const { hoverTime, hoverPercent, handleProgressClick, handleProgressTouch, startDragging } =
  useProgressBar({
    progressBar,
    isDragging,
    getTotalDuration: () => totalDuration.value,
    onSeek: (position) => emit('seek', position),
  })

// Volume helper: clamp + apply + emit
const adjustVolume = (delta) => {
  volumeLevel.value = Math.min(1, Math.max(0, volumeLevel.value + delta))
  onVolumeChange(volumeLevel.value)
}

// Scroll wheel volume control
const handleWheel = (e) => {
  if (e.deltaY < 0) {
    adjustVolume(VOLUME_WHEEL_STEP)
  } else if (e.deltaY > 0) {
    adjustVolume(-VOLUME_WHEEL_STEP)
  }
  showControls()
}

// Keyboard shortcuts
useKeyboardShortcuts({
  ' ': () => togglePlayPause(),
  k: () => togglePlayPause(),
  ArrowLeft: () => skipBackward(),
  ArrowRight: () => skipForward(),
  ArrowUp: () => adjustVolume(VOLUME_KEYBOARD_STEP),
  ArrowDown: () => adjustVolume(-VOLUME_KEYBOARD_STEP),
  m: () => toggleMute(),
  f: () => toggleFullscreen(),
  Escape: () => {
    if (document.fullscreenElement) toggleFullscreen()
  },
})

// Watch fullscreen changes
const checkFullscreen = () => {
  isFullscreen.value = !!document.fullscreenElement
}

onMounted(() => {
  logger.debug('[CustomControls] Component mounted')
  logger.debug('[CustomControls] Props:', {
    contentId: contentId.value,
    contentType: contentType.value,
    player: player.value,
  })

  document.addEventListener('fullscreenchange', checkFullscreen)

  scheduleHideControls()
})

onUnmounted(() => {
  document.removeEventListener('fullscreenchange', checkFullscreen)
})

// Sync volume with video element
watch(
  () => videoElement.value,
  (el) => {
    if (el) {
      volumeLevel.value = el.volume || DEFAULT_VOLUME
      isMuted.value = el.muted || false
    }
  },
  { immediate: true },
)
</script>

<style lang="scss" scoped>
.custom-controls-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  overflow: hidden;
  box-sizing: border-box;
  transition: opacity 0.3s ease;
  cursor: default;

  &.controls-hidden {
    cursor: none;

    .bottom-controls,
    .top-controls {
      opacity: 0;
      pointer-events: none;
    }
  }

  &.controls-visible {
    .bottom-controls,
    .top-controls {
      opacity: 1;
      pointer-events: auto;
    }
  }
}

.seek-loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  z-index: 20;
}

.center-controls {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 5;
}

.center-play-icon {
  background: rgba(0, 0, 0, 0.5);
  border-radius: 50%;
  padding: 20px;
}

.top-controls {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 20px;
  background: linear-gradient(to bottom, rgba(0, 0, 0, 0.7) 0%, transparent 100%);
  display: flex;
  align-items: center;
  gap: 16px;
  transition: opacity 0.3s ease;
}

.title-info {
  flex: 1;

  .title-text {
    color: white;
    font-size: 1.2rem;
    font-weight: 500;
  }

  .subtitle-text {
    color: rgba(255, 255, 255, 0.7);
    font-size: 0.9rem;
  }
}

.bottom-controls {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 0 20px 20px;
  box-sizing: border-box;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.7) 0%, transparent 100%);
  transition: opacity 0.3s ease;
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.progress-container {
  position: relative;
  height: 20px;
  cursor: pointer;
  padding: 8px 0;
  flex: 1;
  touch-action: none;

  &:hover .progress-bar-handle {
    opacity: 1;
    transform: translateX(-50%) scale(1);
  }

  &:hover .progress-bar-bg {
    height: 6px;
  }
}

.progress-bar-bg {
  position: relative;
  height: 4px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 2px;
  transition: height 0.1s ease;
}

.progress-bar-buffered {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 2px;
}

.progress-bar-played {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--q-primary, #1976d2);
  border-radius: 2px;
}

.progress-bar-handle {
  position: absolute;
  top: 50%;
  width: 14px;
  height: 14px;
  background: var(--q-primary, #1976d2);
  border-radius: 50%;
  transform: translateX(-50%) scale(0);
  opacity: 0;
  transition:
    opacity 0.1s ease,
    transform 0.1s ease;
  cursor: grab;

  &:active {
    cursor: grabbing;
    transform: translateX(-50%) scale(1.2);
  }
}

.progress-preview {
  position: absolute;
  bottom: 100%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: white;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  margin-bottom: 8px;
}

.controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.controls-left,
.controls-right {
  display: flex;
  align-items: center;
}

.volume-control {
  display: flex;
  align-items: center;

  .volume-slider {
    width: 80px;
    margin-left: 8px;
  }
}

.time-display {
  color: white;
  font-size: 14px;
  font-variant-numeric: tabular-nums;

  .time-separator {
    opacity: 0.7;
  }
}

// Transitions
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

// Hide native controls
:deep(video::-webkit-media-controls) {
  display: none !important;
}

:deep(video::-webkit-media-controls-enclosure) {
  display: none !important;
}

// Responsive styles for mobile/small screens
@media (max-width: 599px) {
  .bottom-controls {
    padding: 0 10px 10px;
  }

  .top-controls {
    padding: 10px;
    gap: 8px;
  }

  .title-info {
    .title-text {
      font-size: 1rem;
    }

    .subtitle-text {
      font-size: 0.8rem;
    }
  }

  .controls-row {
    gap: 2px;
  }

  .controls-left,
  .controls-right {
    gap: 0;
  }

  .progress-row {
    gap: 8px;
    margin-bottom: 4px;
  }

  .time-display {
    font-size: 12px;
  }
}
</style>
