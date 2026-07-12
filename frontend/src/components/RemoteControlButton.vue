<template>
  <q-btn flat dense round icon="mdi-remote" color="grey-7" :aria-label="$t('remoteControl.title')">
    <q-menu @before-show="loadDevices">
      <q-list style="width: 320px">
        <q-item-label header>{{ $t('remoteControl.title') }}</q-item-label>

        <!-- Loading State -->
        <q-item v-if="devicesLoading">
          <q-item-section avatar>
            <q-spinner color="primary" size="sm" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('remoteControl.loading') }}</q-item-label>
          </q-item-section>
        </q-item>

        <!-- No Devices -->
        <q-item v-else-if="remoteTargets.length === 0">
          <q-item-section avatar>
            <q-icon name="mdi-devices" color="grey" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('remoteControl.noDevices') }}</q-item-label>
            <q-item-label caption>{{ $t('remoteControl.noDevicesHint') }}</q-item-label>
          </q-item-section>
        </q-item>

        <!-- Device List -->
        <template v-else>
          <q-item
            v-for="device in remoteTargets"
            :key="targetKey(device)"
            clickable
            v-close-popup
            @click="selectRemoteDevice(device)"
          >
            <q-item-section avatar>
              <q-icon
                :name="getDeviceIcon(device)"
                :color="device.is_playing || device.is_cast_target ? 'primary' : 'grey'"
              />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{
                device.name || device.browser || $t('remoteControl.unknownDevice')
              }}</q-item-label>
              <q-item-label caption>
                <template v-if="device.is_playing && device.current_media_title">
                  <q-icon name="mdi-play" size="xs" class="q-mr-xs" />
                  {{ device.current_media_title }}
                </template>
                <template v-else-if="device.is_cast_target">
                  {{ castTargetCaption(device) }}
                </template>
                <template v-else>
                  {{ device.platform }} · {{ formatLastActivity(device.last_activity) }}
                </template>
              </q-item-label>
            </q-item-section>
            <q-item-section side v-if="targetKey(selectedRemoteDevice) === targetKey(device)">
              <q-icon name="mdi-check" color="primary" />
            </q-item-section>
          </q-item>
        </template>

        <q-separator v-if="selectedRemoteDevice" />

        <!-- Selected Device Info -->
        <q-item v-if="selectedRemoteDevice" class="bg-grey-9">
          <q-item-section avatar>
            <q-icon name="mdi-cast-connected" color="primary" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-primary">{{ $t('remoteControl.castingTo') }}</q-item-label>
            <q-item-label>{{
              selectedRemoteDevice.name || selectedRemoteDevice.browser
            }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn flat round dense icon="mdi-close" @click.stop="clearRemoteDevice" />
          </q-item-section>
        </q-item>

        <q-item v-if="selectedRemoteDevice && selectedRemoteDevice.is_cast_target" dense>
          <q-item-section avatar>
            <q-spinner v-if="castStatusLoading" color="primary" size="sm" />
            <q-icon v-else name="mdi-cast-audio" color="grey-5" />
          </q-item-section>
          <q-item-section>
            <q-item-label caption>{{ castStatusSummary }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              flat
              round
              dense
              icon="mdi-refresh"
              :aria-label="$t('common.refresh')"
              @click.stop="refreshSelectedCastStatus"
            />
          </q-item-section>
        </q-item>

        <q-item v-if="selectedRemoteDevice && !selectedRemoteDevice.is_cast_target" dense>
          <q-item-section avatar>
            <q-spinner v-if="sessionLoading" color="primary" size="sm" />
            <q-icon v-else name="mdi-card-account-details-outline" color="grey-5" />
          </q-item-section>
          <q-item-section>
            <q-item-label caption>
              <template v-if="sessionLoading">
                {{ $t('remoteControl.loadingSession') }}
              </template>
              <template v-else-if="sessionCapabilities">
                {{ sessionSummary }}
              </template>
              <template v-else>
                {{ $t('remoteControl.sessionUnavailable') }}
              </template>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              flat
              round
              dense
              icon="mdi-refresh"
              :aria-label="$t('common.refresh')"
              @click.stop="refreshSelectedSession"
            />
          </q-item-section>
        </q-item>

        <q-item v-if="selectedRemoteDevice && selectedSupportsMessage" dense>
          <q-item-section>
            <q-btn
              flat
              no-caps
              icon="mdi-message-text-outline"
              :label="$t('remoteControl.sendMessage')"
              @click.stop="openMessageDialog"
            />
          </q-item-section>
        </q-item>

        <!-- Transport Controls (when device is selected and playing) -->
        <template v-if="hasSelectedTransport">
          <q-separator />

          <!-- Current media title -->
          <q-item v-if="selectedPlaybackTitle" dense>
            <q-item-section>
              <q-item-label class="text-center text-caption ellipsis">
                {{ selectedPlaybackTitle }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <!-- Position / Duration -->
          <q-item v-if="selectedPlaybackDuration > 0" dense>
            <q-item-section>
              <q-item-label class="text-center text-caption text-grey">
                {{ formatTime(selectedPlaybackPosition) }}
                /
                {{ formatTime(selectedPlaybackDuration) }}
              </q-item-label>
            </q-item-section>
          </q-item>

          <!-- Transport buttons row -->
          <q-item dense v-if="!selectedRemoteDevice.is_cast_target">
            <q-item-section>
              <div class="row justify-center items-center q-gutter-xs">
                <q-btn
                  v-if="selectedSupportsQueue"
                  flat
                  round
                  dense
                  icon="mdi-skip-previous"
                  :aria-label="$t('remoteControl.previous')"
                  :disable="!isCommandSupported('previous')"
                  @click.stop="remoteControlStore.sendPreviousCommand()"
                />
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-rewind-10"
                  :aria-label="$t('remoteControl.skipBackward')"
                  :disable="!isCommandSupported('skip_backward')"
                  @click.stop="remoteControlStore.sendSkipBackwardCommand(10)"
                />
                <q-btn
                  flat
                  round
                  dense
                  :icon="selectedIsPlaying ? 'mdi-pause' : 'mdi-play'"
                  :aria-label="
                    selectedIsPlaying
                      ? $t('remoteControl.pauseCommand')
                      : $t('remoteControl.playCommand')
                  "
                  size="lg"
                  :disable="!isCommandSupported(selectedPlayPauseCommand)"
                  @click.stop="togglePlayPause"
                />
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-fast-forward-10"
                  :aria-label="$t('remoteControl.skipForward')"
                  :disable="!isCommandSupported('skip_forward')"
                  @click.stop="remoteControlStore.sendSkipForwardCommand(10)"
                />
                <q-btn
                  v-if="selectedSupportsQueue"
                  flat
                  round
                  dense
                  icon="mdi-skip-next"
                  :aria-label="$t('remoteControl.next')"
                  :disable="!isCommandSupported('next')"
                  @click.stop="remoteControlStore.sendNextCommand()"
                />
              </div>
            </q-item-section>
          </q-item>

          <q-item dense v-else>
            <q-item-section>
              <div class="row justify-center items-center q-gutter-sm">
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-pause"
                  :aria-label="$t('remoteControl.pauseCommand')"
                  :disable="!isCommandSupported('pause')"
                  @click.stop="remoteControlStore.sendPauseCommand()"
                />
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-play"
                  :aria-label="$t('remoteControl.playCommand')"
                  :disable="!isCommandSupported('resume')"
                  @click.stop="remoteControlStore.sendResumeCommand()"
                />
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-stop"
                  :aria-label="$t('remoteControl.stopCommand')"
                  :disable="!isCommandSupported('stop')"
                  @click.stop="remoteControlStore.sendStopCommand()"
                />
              </div>
            </q-item-section>
          </q-item>

          <!-- Volume controls -->
          <q-item dense v-if="selectedSupportsVolume">
            <q-item-section side>
              <q-btn
                flat
                round
                dense
                :icon="isMuted ? 'mdi-volume-off' : 'mdi-volume-high'"
                :aria-label="$t('remoteControl.mute')"
                :disable="!isCommandSupported('mute')"
                @click.stop="toggleMute"
              />
            </q-item-section>
            <q-item-section>
              <q-slider
                :model-value="volumeLevel"
                :min="0"
                :max="1"
                :step="0.01"
                color="primary"
                :aria-label="$t('remoteControl.volume')"
                :disable="!isCommandSupported('volume')"
                @update:model-value="onVolumeChange"
              />
            </q-item-section>
          </q-item>
        </template>
      </q-list>
    </q-menu>
  </q-btn>

  <q-dialog v-model="messageDialogOpen">
    <q-card style="min-width: 320px">
      <q-card-section>
        <div class="text-h6">{{ $t('remoteControl.sendMessage') }}</div>
      </q-card-section>
      <q-card-section class="q-gutter-md">
        <q-input v-model="messageTitle" :label="$t('remoteControl.messageTitle')" dense outlined />
        <q-input
          v-model="messageText"
          :label="$t('remoteControl.messageText')"
          type="textarea"
          autogrow
          dense
          outlined
        />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat :label="$t('common.cancel')" v-close-popup />
        <q-btn
          color="primary"
          :label="$t('remoteControl.sendMessageAction')"
          :disable="!messageText.trim()"
          :loading="messageSending"
          @click="sendMessage"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from 'stores/auth'
import { useRemoteControlStore } from 'stores/remoteControl'
import { getMyDevices, discoverCastTargets } from 'src/services/mediaComponentsService'
import { logger } from 'src/utils/logger'
const { t } = useI18n()
const authStore = useAuthStore()
const remoteControlStore = useRemoteControlStore()

const devicesLoading = ref(false)
const userDevices = ref([])
const castTargets = ref([])
const selectedRemoteDevice = computed(() => remoteControlStore.targetDevice)
const sessionLoading = computed(() => remoteControlStore.targetSessionLoading)
const castStatusLoading = computed(() => remoteControlStore.targetCastStatusLoading)
const sessionCapabilities = computed(() => remoteControlStore.targetCapabilities)
const sessionNowPlaying = computed(() => remoteControlStore.targetNowPlaying)
const sessionQueueState = computed(() => remoteControlStore.targetQueueState)
const castStatus = computed(() => remoteControlStore.targetCastStatus)
const volumeLevel = ref(0.5)
const isMuted = ref(false)
const messageDialogOpen = ref(false)
const messageTitle = ref('')
const messageText = ref('')
const messageSending = ref(false)

// Filter out current device and offline devices
const otherDevices = computed(() => {
  const currentDeviceId = authStore.deviceId
  return userDevices.value.filter(
    (device) => device.device_id !== currentDeviceId && device.is_ws_connected,
  )
})

const remoteTargets = computed(() => [...otherDevices.value, ...castTargets.value])
const selectedSupportsVolume = computed(() => remoteControlStore.supportsVolumeControl)
const selectedSupportsQueue = computed(() => remoteControlStore.supportsQueueControl)
const selectedSupportsMessage = computed(() => remoteControlStore.supportsDisplayMessage)
const selectedIsPlaying = computed(
  () => sessionNowPlaying.value?.is_playing ?? selectedRemoteDevice.value?.is_playing ?? false,
)
const selectedPlayPauseCommand = computed(() => (selectedIsPlaying.value ? 'pause' : 'resume'))
const selectedPlaybackTitle = computed(
  () =>
    sessionNowPlaying.value?.media_title || selectedRemoteDevice.value?.current_media_title || '',
)
const selectedPlaybackPosition = computed(
  () =>
    sessionNowPlaying.value?.position_seconds ||
    selectedRemoteDevice.value?.current_playback_position ||
    0,
)
const selectedPlaybackDuration = computed(
  () =>
    sessionNowPlaying.value?.duration_seconds ||
    selectedRemoteDevice.value?.current_playback_duration ||
    0,
)
const hasSelectedTransport = computed(
  () =>
    !!selectedRemoteDevice.value &&
    (selectedRemoteDevice.value.is_cast_target ||
      !!sessionNowPlaying.value ||
      !!selectedRemoteDevice.value.is_playing),
)
const sessionSummary = computed(() => {
  const parts = []
  if (sessionCapabilities.value?.profile_id) {
    parts.push(sessionCapabilities.value.profile_id)
  }
  if (sessionCapabilities.value?.supports_play_queue) {
    parts.push(t('remoteControl.queueSupported'))
  }
  const queueCount = sessionQueueState.value?.items?.length || 0
  if (queueCount > 0) {
    parts.push(t('remoteControl.queueItems', { count: queueCount }))
  }
  return parts.length ? parts.join(' · ') : t('remoteControl.sessionReady')
})
const castStatusSummary = computed(() => {
  if (castStatusLoading.value) return t('remoteControl.loadingStatus')
  if (!castStatus.value) return t('remoteControl.statusUnavailable')
  const parts = [
    castStatus.value.transport_state,
    castStatus.value.position && castStatus.value.duration
      ? `${castStatus.value.position} / ${castStatus.value.duration}`
      : null,
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : t('remoteControl.statusReady')
})

// Load user devices
async function loadDevices() {
  if (devicesLoading.value) return
  devicesLoading.value = true
  try {
    const [devicesResult, castResult] = await Promise.allSettled([
      getMyDevices({ page_size: 50 }),
      discoverCastTargets({ native: true }),
    ])
    if (devicesResult.status === 'fulfilled') {
      userDevices.value = devicesResult.value.items || []
    } else {
      logger.error('Failed to load devices:', devicesResult.reason)
    }
    if (castResult.status === 'fulfilled') {
      castTargets.value = (castResult.value.items || [])
        .filter((target) => target.enabled && target.protocol !== 'pyrate')
        .map((target) => ({
          ...target,
          is_cast_target: true,
          guid: target.id,
        }))
    } else {
      logger.error('Failed to load cast targets:', castResult.reason)
    }
    if (selectedRemoteDevice.value && !selectedRemoteDevice.value.is_cast_target) {
      remoteControlStore.loadTargetSession(selectedRemoteDevice.value)
    }
  } catch (error) {
    logger.error('Failed to load devices:', error)
  } finally {
    devicesLoading.value = false
  }
}

// Select a remote device to cast to
function selectRemoteDevice(device) {
  remoteControlStore.setTargetDevice(device)
  if (device.is_cast_target) {
    remoteControlStore.loadCastTargetStatus(device)
  } else {
    remoteControlStore.loadTargetSession(device)
  }
}

// Clear remote device selection
function clearRemoteDevice() {
  remoteControlStore.clearTargetDevice()
}

function refreshSelectedSession() {
  remoteControlStore.loadTargetSession(selectedRemoteDevice.value)
}

function refreshSelectedCastStatus() {
  remoteControlStore.loadCastTargetStatus(selectedRemoteDevice.value)
}

function isCommandSupported(command) {
  return remoteControlStore.isCommandSupported(command)
}

// Get device icon based on platform
function getDeviceIcon(device) {
  if (device?.protocol === 'chromecast') return 'mdi-cast'
  if (device?.protocol === 'dlna') return 'mdi-television-classic'
  if (device?.protocol === 'airplay') return 'mdi-apple-airplay'
  const platform = device.platform?.toLowerCase() || ''
  if (platform.includes('windows')) return 'mdi-microsoft-windows'
  if (platform.includes('mac')) return 'mdi-apple'
  if (platform.includes('linux')) return 'mdi-linux'
  if (platform.includes('android')) return 'mdi-android'
  if (platform.includes('ios')) return 'mdi-apple-ios'
  return 'mdi-devices'
}

function targetKey(device) {
  if (!device) return null
  return device.is_cast_target ? `cast:${device.id}` : `device:${device.guid || device.device_id}`
}

function castTargetCaption(device) {
  const protocol = device.protocol ? device.protocol.toUpperCase() : t('remoteControl.unknown')
  if (device.discovery_source) return `${protocol} · ${device.discovery_source}`
  return protocol
}

// Toggle play/pause on remote device
function togglePlayPause() {
  if (selectedIsPlaying.value) {
    remoteControlStore.sendPauseCommand()
  } else {
    remoteControlStore.sendResumeCommand()
  }
}

// Toggle mute on remote device
function toggleMute() {
  isMuted.value = !isMuted.value
  remoteControlStore.sendMuteCommand()
}

// Handle volume slider change
function onVolumeChange(val) {
  volumeLevel.value = val
  remoteControlStore.sendVolumeCommand(val)
}

function openMessageDialog() {
  messageTitle.value = ''
  messageText.value = ''
  messageDialogOpen.value = true
}

async function sendMessage() {
  if (!messageText.value.trim()) return
  messageSending.value = true
  try {
    const sent = await remoteControlStore.sendMessageCommand({
      title: messageTitle.value.trim() || null,
      text: messageText.value.trim(),
    })
    if (sent) {
      messageDialogOpen.value = false
      messageText.value = ''
      messageTitle.value = ''
    }
  } finally {
    messageSending.value = false
  }
}

// Format seconds to mm:ss or hh:mm:ss
function formatTime(totalSeconds) {
  const seconds = Math.floor(totalSeconds % 60)
  const minutes = Math.floor((totalSeconds / 60) % 60)
  const hours = Math.floor(totalSeconds / 3600)
  const pad = (n) => String(n).padStart(2, '0')
  if (hours > 0) {
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
  }
  return `${pad(minutes)}:${pad(seconds)}`
}

// Format last activity timestamp
function formatLastActivity(timestamp) {
  if (!timestamp) return t('remoteControl.unknown')
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return t('remoteControl.justNow')
  if (diffMins < 60) return t('remoteControl.minutesAgo', { count: diffMins })
  if (diffHours < 24) return t('remoteControl.hoursAgo', { count: diffHours })
  return t('remoteControl.daysAgo', { count: diffDays })
}
</script>
