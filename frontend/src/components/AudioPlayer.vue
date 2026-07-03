<template>
  <transition name="slide-up">
    <div v-if="playerStore.isVisible" class="audio-player">
      <!-- Progress bar at top of player -->
      <div class="progress-bar-container" @click="onProgressClick" @mousedown="onProgressDragStart">
        <div class="progress-bar-bg" />
        <div class="progress-bar-fill" :style="{ width: `${playerStore.progress * 100}%` }" />
        <div class="progress-bar-handle" :style="{ left: `${playerStore.progress * 100}%` }" />
      </div>

      <div class="audio-player-content row items-center no-wrap q-px-sm">
        <!-- Track info (left) -->
        <div class="track-info row items-center no-wrap col-shrink">
          <q-avatar
            v-if="playerStore.currentTrack?.albumArt"
            size="48px"
            square
            class="q-mr-sm album-art"
          >
            <q-img
              :src="playerStore.currentTrack.albumArt"
              :alt="playerStore.currentTrack.albumTitle || playerStore.currentTrack.title"
            />
          </q-avatar>
          <q-avatar v-else size="48px" square class="q-mr-sm album-art bg-grey-8">
            <q-icon name="mdi-music-note" color="grey-5" />
          </q-avatar>

          <div class="text-section" style="min-width: 0">
            <div class="text-body2 text-white ellipsis">
              {{ playerStore.currentTrack?.title || $t('audioPlayer.noTrack') }}
            </div>
            <div
              v-if="playerStore.currentTrack?.artist || playerStore.currentTrack?.albumTitle"
              class="text-caption text-grey-5 ellipsis"
            >
              <a
                v-if="playerStore.currentTrack?.artistGuid"
                class="artist-link"
                @click.stop="router.push(`/media/${playerStore.currentTrack.artistGuid}`)"
              >
                {{ playerStore.currentTrack.artist }}
              </a>
              <span v-else-if="playerStore.currentTrack?.artist">{{
                playerStore.currentTrack.artist
              }}</span>
              <template
                v-if="playerStore.currentTrack?.artist && playerStore.currentTrack?.albumTitle"
              >
                ·
              </template>
              <a
                v-if="playerStore.currentTrack?.albumGuid"
                class="artist-link"
                @click.stop="router.push(`/media/${playerStore.currentTrack.albumGuid}`)"
              >
                {{ playerStore.currentTrack.albumTitle }}
              </a>
              <span v-else-if="playerStore.currentTrack?.albumTitle">{{
                playerStore.currentTrack.albumTitle
              }}</span>
            </div>
          </div>
        </div>

        <q-space />

        <!-- Playback controls (center) -->
        <div class="playback-controls row items-center no-wrap">
          <q-btn
            flat
            round
            dense
            :icon="shuffleIcon"
            :color="playerStore.shuffle ? 'primary' : 'grey-5'"
            size="sm"
            class="gt-xs"
            @click="playerStore.toggleShuffle()"
          />
          <q-btn
            flat
            round
            dense
            icon="mdi-skip-previous"
            color="white"
            size="md"
            :disable="!playerStore.hasPrevious"
            @click="playerStore.previous()"
          />
          <q-btn
            round
            :icon="playPauseIcon"
            color="white"
            text-color="dark"
            size="md"
            :loading="playerStore.isLoading"
            @click="playerStore.togglePlay()"
          />
          <q-btn
            flat
            round
            dense
            icon="mdi-skip-next"
            color="white"
            size="md"
            :disable="!playerStore.hasNext"
            @click="playerStore.next()"
          />
          <q-btn
            flat
            round
            dense
            :icon="repeatIcon"
            :color="playerStore.repeat !== 'off' ? 'primary' : 'grey-5'"
            size="sm"
            class="gt-xs"
            @click="playerStore.toggleRepeat()"
          />
        </div>

        <q-space />

        <!-- Time display + Volume + Close (right) -->
        <div class="right-controls row items-center no-wrap col-shrink">
          <!-- Time display -->
          <div class="time-display text-caption text-grey-5 q-mr-sm gt-xs">
            {{ playerStore.formattedCurrentTime }} / {{ playerStore.formattedDuration }}
          </div>

          <!-- Volume -->
          <div class="volume-control row items-center no-wrap gt-sm">
            <q-btn
              flat
              round
              dense
              :icon="volumeIcon"
              color="grey-5"
              size="sm"
              @click="toggleMute"
            />
            <q-slider
              :model-value="playerStore.volume"
              :min="0"
              :max="1"
              :step="0.01"
              color="white"
              track-size="3px"
              thumb-size="12px"
              style="width: 80px"
              @update:model-value="playerStore.setVolume($event)"
            />
          </div>

          <!-- Queue button -->
          <q-btn
            flat
            round
            dense
            icon="mdi-text-box-music-outline"
            :color="playerStore.lyrics ? 'primary' : 'grey-5'"
            size="sm"
            class="q-ml-xs"
            :loading="playerStore.lyricsLoading"
            @click="showLyrics = true"
          />

          <q-btn
            flat
            round
            dense
            icon="mdi-playlist-music"
            color="grey-5"
            size="sm"
            class="q-ml-xs"
          >
            <q-menu anchor="top right" self="bottom right" class="bg-dark" max-height="400px">
              <q-list dark dense separator style="min-width: 280px">
                <q-item-label header class="text-grey-4">
                  {{ $t('audioPlayer.queue') }} ({{ playerStore.queue.length }})
                </q-item-label>
                <q-item
                  v-for="(track, idx) in playerStore.queue"
                  :key="idx"
                  clickable
                  :active="idx === playerStore.queueIndex"
                  active-class="bg-grey-8"
                  @click="playFromQueue(idx)"
                >
                  <q-item-section avatar>
                    <q-icon
                      :name="
                        idx === playerStore.queueIndex && playerStore.isPlaying
                          ? 'mdi-volume-high'
                          : 'mdi-music-note'
                      "
                      :color="idx === playerStore.queueIndex ? 'primary' : 'grey-5'"
                      size="xs"
                    />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label class="ellipsis">{{ track.title }}</q-item-label>
                    <q-item-label caption class="ellipsis">{{ track.artist }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-btn
                      flat
                      round
                      dense
                      icon="mdi-close"
                      size="xs"
                      color="grey-5"
                      @click.stop="playerStore.removeFromQueue(idx)"
                    />
                  </q-item-section>
                </q-item>
                <q-item v-if="playerStore.queue.length === 0">
                  <q-item-section class="text-grey-5 text-center">
                    {{ $t('audioPlayer.emptyQueue') }}
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>

          <!-- Close button -->
          <q-btn
            flat
            round
            dense
            icon="mdi-close"
            color="grey-5"
            size="sm"
            class="q-ml-xs"
            @click="playerStore.close()"
          />
        </div>
      </div>

      <q-dialog v-model="showLyrics" position="bottom">
        <q-card dark class="lyrics-card">
          <q-card-section class="row items-center no-wrap q-pb-sm">
            <div class="col">
              <div class="text-subtitle1 ellipsis">
                {{ playerStore.currentTrack?.title || 'Lyrics' }}
              </div>
              <div class="text-caption text-grey-5 ellipsis">
                {{ playerStore.currentTrack?.artist || '' }}
              </div>
              <q-chip
                v-if="playerStore.lyrics"
                dense
                size="sm"
                :color="playerStore.lyrics.synced ? 'positive' : 'blue-grey-8'"
                text-color="white"
                class="q-mt-xs"
              >
                {{
                  playerStore.lyrics.synced
                    ? $t('mediaDetail.syncedLyrics')
                    : $t('mediaDetail.plainLyrics')
                }}
              </q-chip>
            </div>
            <q-btn flat round dense icon="mdi-refresh" @click="playerStore.loadLyrics()" />
            <q-btn v-close-popup flat round dense icon="mdi-close" />
          </q-card-section>
          <q-separator dark />
          <q-card-section class="lyrics-body">
            <q-spinner-dots v-if="playerStore.lyricsLoading" color="primary" size="32px" />
            <pre v-else-if="playerStore.lyrics?.lyrics" class="lyrics-text">{{
              playerStore.lyrics.lyrics
            }}</pre>
            <div v-else class="text-grey-5">No lyrics available</div>
          </q-card-section>
        </q-card>
      </q-dialog>
    </div>
  </transition>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAudioPlayerStore } from 'src/stores/audioPlayer'

const router = useRouter()
const playerStore = useAudioPlayerStore()
const previousVolume = ref(0.8)
const showLyrics = ref(false)

const playPauseIcon = computed(() => {
  if (playerStore.isLoading) return 'mdi-loading'
  return playerStore.isPlaying ? 'mdi-pause' : 'mdi-play'
})

const shuffleIcon = computed(() => 'mdi-shuffle-variant')

const repeatIcon = computed(() => {
  if (playerStore.repeat === 'one') return 'mdi-repeat-once'
  return 'mdi-repeat'
})

const volumeIcon = computed(() => {
  if (playerStore.volume === 0) return 'mdi-volume-off'
  if (playerStore.volume < 0.3) return 'mdi-volume-low'
  if (playerStore.volume < 0.7) return 'mdi-volume-medium'
  return 'mdi-volume-high'
})

function toggleMute() {
  if (playerStore.volume > 0) {
    previousVolume.value = playerStore.volume
    playerStore.setVolume(0)
  } else {
    playerStore.setVolume(previousVolume.value || 0.8)
  }
}

function onProgressClick(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const percent = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
  playerStore.seekPercent(percent)
}

function onProgressDragStart(event) {
  const container = event.currentTarget

  function onMouseMove(e) {
    const rect = container.getBoundingClientRect()
    const percent = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    playerStore.seekPercent(percent)
  }

  function onMouseUp() {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  }

  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

async function playFromQueue(idx) {
  playerStore.queueIndex = idx
  await playerStore._loadAndPlay(playerStore.queue[idx])
}
</script>

<style lang="scss" scoped>
.audio-player {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 2000;
  background: var(--q-dark, #1d1d1d);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.audio-player-content {
  height: 64px;
}

.artist-link {
  color: inherit;
  text-decoration: none;
  cursor: pointer;

  &:hover {
    color: white;
    text-decoration: underline;
  }
}

// Progress bar
.progress-bar-container {
  position: relative;
  height: 4px;
  cursor: pointer;
  transition: height 0.15s ease;

  &:hover {
    height: 6px;

    .progress-bar-handle {
      opacity: 1;
      transform: translateX(-50%) scale(1);
    }
  }
}

.progress-bar-bg {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.15);
}

.progress-bar-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  background: var(--q-primary, #1976d2);
  transition: width 0.1s linear;
}

.progress-bar-handle {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: white;
  transform: translateX(-50%) scale(0);
  transition:
    opacity 0.15s,
    transform 0.15s;
  opacity: 0;
  margin-top: -6px;
}

// Track info
.track-info {
  max-width: 250px;
}

.album-art {
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
}

.text-section {
  overflow: hidden;
}

// Right controls
.time-display {
  white-space: nowrap;
}

.lyrics-card {
  width: min(720px, 100vw);
  max-height: min(70vh, 640px);
}

.lyrics-body {
  max-height: calc(min(70vh, 640px) - 76px);
  overflow: auto;
}

.lyrics-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.95rem;
  line-height: 1.7;
  color: white;
}

// Transitions
.slide-up-enter-active,
.slide-up-leave-active {
  transition:
    transform 0.3s ease,
    opacity 0.3s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

// Responsive
@media (max-width: 599px) {
  .track-info {
    max-width: 120px;
  }
}
</style>
