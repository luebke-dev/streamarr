<template>
  <div class="game-stream-wrapper">
    <!-- Loading / Launching -->
    <div v-if="!streaming" class="flex flex-center loading-container">
      <div class="text-center">
        <q-spinner-dots size="56px" color="primary" class="q-mb-md" />
        <div class="text-body1 text-grey-3">{{ statusText || $t('playPage.launchingGame') }}</div>
        <q-btn
          flat
          color="grey-6"
          :label="$t('playPage.cancel')"
          @click="onBack"
          class="q-mt-xl"
        />
      </div>
    </div>

    <!-- Stream View -->
    <div v-show="streaming" ref="streamContainerRef" class="stream-container">
      <!-- Toolbar (Ctrl+M) -->
      <div class="stream-toolbar" :class="{ visible: toolbarVisible }">
        <q-btn flat dense size="sm" icon="mdi-fullscreen" tabindex="-1" @click="onFullscreen">
          <span class="gt-md q-ml-xs">{{ $t('playPage.gameFullscreen') }}</span>
          <q-tooltip class="lt-lg">{{ $t('playPage.gameFullscreen') }}</q-tooltip>
        </q-btn>
        <q-btn
          flat
          dense
          size="sm"
          icon="mdi-mouse"
          tabindex="-1"
          @click="stream.togglePointerLock()"
        >
          <span class="gt-md q-ml-xs">{{ $t('playPage.gamePointerLock') }}</span>
          <q-tooltip class="lt-lg">{{ $t('playPage.gamePointerLock') }}</q-tooltip>
        </q-btn>
        <q-btn
          flat
          dense
          size="sm"
          :icon="showDebug ? 'mdi-bug-check' : 'mdi-bug'"
          tabindex="-1"
          @click="showDebug = !showDebug"
        >
          <span class="gt-md q-ml-xs">Debug</span>
        </q-btn>
        <span class="stats-text text-caption text-grey-5 q-ml-sm">
          {{ stats.mbps }} Mbps | {{ stats.fps }} fps | {{ stats.rtt }}ms
        </span>
        <q-space />
        <q-btn
          flat
          dense
          size="sm"
          icon="mdi-close"
          color="negative"
          tabindex="-1"
          @click="onDisconnect"
        >
          <span class="gt-md q-ml-xs">{{ $t('playPage.gameDisconnect') }}</span>
          <q-tooltip class="lt-lg">{{ $t('playPage.gameDisconnect') }}</q-tooltip>
        </q-btn>
      </div>
      <video ref="videoRef" autoplay playsinline muted class="stream-video" />
      <!-- Debug overlay -->
      <div v-if="showDebug" class="debug-overlay">
        <div class="debug-title">Stream Debug</div>
        <div>Resolution: {{ stats.resolution }}</div>
        <div>Codec: {{ stats.codec }}</div>
        <div>FPS: {{ stats.fps }}</div>
        <div>Bitrate: {{ stats.mbps }} Mbps</div>
        <div>RTT: {{ stats.rtt }}ms</div>
        <div>Jitter: {{ stats.jitter }}ms</div>
        <div>Decode: {{ stats.decodeTime }}ms/frame</div>
        <div>Packets lost: {{ stats.packetsLost }}</div>
        <div>Frames decoded: {{ stats.frames }}</div>
      </div>
    </div>

    <!-- Error -->
    <div v-if="status === 'error'" class="flex flex-center loading-container">
      <div class="text-center">
        <q-icon name="mdi-alert-circle" size="80px" color="negative" />
        <div class="text-h5 text-white q-mt-lg">{{ $t('playPage.error') }}</div>
        <div class="text-body1 text-grey-4 q-mt-sm q-mb-lg">{{ statusText }}</div>
        <div class="q-gutter-sm">
          <q-btn color="primary" :label="$t('playPage.retry')" @click="$emit('retry')" />
          <q-btn color="grey-7" :label="$t('playPage.goBack')" outline @click="onBack" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useLightraysStreaming } from 'src/composables/useLightraysStreaming'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const showDebug = ref(false)

const props = defineProps({
  sessionId: { type: String, required: true },
  wsTicket: { type: String, default: '' },
  websocketUrl: { type: String, default: '' },
  iceServers: { type: Array, default: () => [] },
  gameTitle: { type: String, default: '' },
})

const emit = defineEmits(['back', 'retry', 'disconnected'])

const stream = useLightraysStreaming()
const { status, statusText, streaming, stats } = stream

const videoRef = ref(null)
const streamContainerRef = ref(null)
const toolbarVisible = ref(true)

// Connect to Lightrays WebSocket signaling as soon as we have session info
onMounted(() => {
  window.addEventListener('keydown', onKeyDown, true)
  connectToSession()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown, true)
  stream.stopStream()
})

async function connectToSession() {
  // The backend already launched the session; we just connect the WS
  stream.connectWebSocket(props.sessionId, props.wsTicket, props.iceServers, props.websocketUrl)

  // Bind input once video element is available
  await nextTick()
  pollBindInput()
}

function pollBindInput() {
  // Video element may not be in DOM yet (v-show). Poll briefly.
  let tries = 0
  const iv = setInterval(() => {
    tries++
    if (videoRef.value && streamContainerRef.value) {
      stream.bindInput(videoRef.value, streamContainerRef.value)
      clearInterval(iv)
    } else if (tries > 50) {
      clearInterval(iv)
    }
  }, 100)
}

// Expose connectWebSocket for external use (re-use the composable's method)
watch(streaming, (val) => {
  if (!val && status.value !== 'error' && status.value !== 'idle') {
    // streaming ended unexpectedly
  }
})

function onKeyDown(e) {
  if (e.ctrlKey && e.key === 'm') {
    e.preventDefault()
    e.stopPropagation()
    toolbarVisible.value = !toolbarVisible.value
  }
}

function onFullscreen() {
  stream.toggleFullscreen()
  document.activeElement?.blur()
  toolbarVisible.value = false
}

async function stopRemoteSession() {
  if (!props.sessionId) return
  try {
    await api.post('/api/lightrays/stop', { session_id: props.sessionId })
  } catch (e) {
    logger.debug('Failed to stop Lightrays session', e)
  }
}

async function onBack() {
  await stopRemoteSession()
  emit('back')
}

async function onDisconnect() {
  await stopRemoteSession()
  stream.stopStream()
  emit('disconnected')
}
</script>

<style lang="scss" scoped>
.game-stream-wrapper {
  width: 100%;
  height: 100%;
  background: #000;
}

.loading-container {
  width: 100%;
  height: 100vh;
  background: rgba(0, 0, 0, 0.95);
}

.stream-container {
  position: relative;
  width: 100%;
  height: calc(100vh - 50px); // subtract q-header height
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;

  &:fullscreen,
  &:-webkit-full-screen {
    width: 100vw;
    height: 100vh;
  }
}

.stream-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  cursor: none;
}

.debug-overlay {
  position: absolute;
  top: 48px;
  right: 12px;
  background: rgba(0, 0, 0, 0.85);
  color: #0f0;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid rgba(0, 255, 0, 0.3);
  z-index: 20;
  pointer-events: none;
  line-height: 1.6;

  .debug-title {
    font-weight: bold;
    color: #0ff;
    margin-bottom: 4px;
    font-size: 13px;
  }
}

.stream-toolbar {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(22, 27, 34, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-top: none;
  border-radius: 0 0 8px 8px;
  padding: 4px 16px;
  display: flex;
  gap: 8px;
  align-items: center;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
  z-index: 10;
  white-space: nowrap;

  &.visible {
    opacity: 1;
    pointer-events: auto;
  }
}

.stats-text {
  font-size: 11px;
}
</style>
