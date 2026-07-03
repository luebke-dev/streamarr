import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useWebSocket } from 'src/composables/useWebSocket'
import { useAuthStore } from './auth'
import { logger } from 'src/utils/logger'
import { api } from 'boot/axios'

export const useRemoteControlStore = defineStore('remoteControl', () => {
  // State
  const targetDevice = ref(null)
  const targetSession = ref(null)
  const targetSessionLoading = ref(false)
  const targetSessionError = ref(null)
  const targetCastStatus = ref(null)
  const targetCastStatusLoading = ref(false)
  const targetCastStatusError = ref(null)
  const isRemoteControlled = ref(false)
  const remoteController = ref(null)

  // Stores
  const ws = useWebSocket()
  const authStore = useAuthStore()

  // Computed
  const isControllingRemote = computed(() => targetDevice.value !== null)
  const hasRemoteTarget = computed(() => !!targetDevice.value)
  const targetCapabilities = computed(() => targetSession.value?.capabilities || null)
  const targetNowPlaying = computed(() => targetSession.value?.now_playing || null)
  const targetQueueState = computed(() => targetSession.value?.queue_state || null)
  const supportedCommands = computed(() => {
    const device = targetDevice.value
    if (!device) return []
    if (isNativeCastTarget(device)) {
      if (Array.isArray(device.supported_commands)) return device.supported_commands
      if (device.protocol === 'chromecast') {
        return ['play', 'pause', 'resume', 'stop', 'seek', 'play_queue', 'volume', 'mute']
      }
      if (device.protocol === 'dlna') return ['play', 'pause', 'resume', 'stop', 'seek']
      if (device.protocol === 'airplay') return ['play', 'pause', 'resume', 'stop']
      return []
    }
    return Array.isArray(targetCapabilities.value?.supported_commands)
      ? targetCapabilities.value.supported_commands
      : []
  })
  const supportsVolumeControl = computed(() => {
    const device = targetDevice.value
    if (!device) return false
    if (isNativeCastTarget(device)) {
      return Boolean(device.supports_volume_control || device.protocol === 'chromecast')
    }
    return Boolean(targetCapabilities.value?.supports_volume_control)
  })
  const supportsQueueControl = computed(() => {
    const device = targetDevice.value
    if (!device) return false
    if (isNativeCastTarget(device)) {
      return supportedCommands.value.some((command) =>
        ['play_queue', 'queue_load', 'queue', 'next', 'previous'].includes(command),
      )
    }
    return Boolean(targetCapabilities.value?.supports_play_queue)
  })
  const supportsDisplayMessage = computed(
    () =>
      Boolean(targetCapabilities.value?.supports_display_message) && isCommandSupported('message'),
  )

  // Set target device for remote control
  function setTargetDevice(device) {
    targetDevice.value = device
    targetSession.value = null
    targetSessionError.value = null
    targetCastStatus.value = null
    targetCastStatusError.value = null
    logger.debug('[RemoteControl] Target device set:', device.name || device.browser)
  }

  // Clear target device
  function clearTargetDevice() {
    targetDevice.value = null
    targetSession.value = null
    targetSessionError.value = null
    targetCastStatus.value = null
    targetCastStatusError.value = null
    logger.debug('[RemoteControl] Target device cleared')
  }

  // Send remote command to target device
  function isNativeCastTarget(target) {
    return !!target?.protocol && target.protocol !== 'pyrate'
  }

  function playbackProfileForTarget(target) {
    if (!target) return null
    if (target.playback_profile || target.profile_id) {
      return target.playback_profile || target.profile_id
    }
    if (target.protocol === 'chromecast') return 'chromecast'
    if (target.protocol === 'dlna') return 'dlna_generic'
    if (target.protocol === 'airplay') return 'browser'
    return null
  }

  function playbackOptionsForTarget(target = targetDevice.value) {
    if (!target) return {}
    const options = {}
    const profileId = playbackProfileForTarget(target)
    if (profileId) {
      options.profile_id = profileId
    }
    if (!isNativeCastTarget(target) && target.guid) {
      options.device_guid = target.guid
    }
    return options
  }

  async function sendCastTargetCommand(command, payload = {}) {
    const target = targetDevice.value
    try {
      await api.post(`/api/cast/targets/${encodeURIComponent(target.id)}/commands`, {
        command,
        payload,
      })
      await loadCastTargetStatus(target)
      return true
    } catch (error) {
      logger.error('[RemoteControl] Cast target command failed:', error)
      return false
    }
  }

  async function loadCastTargetStatus(target = targetDevice.value) {
    if (!target || !isNativeCastTarget(target) || !target.id) {
      targetCastStatus.value = null
      targetCastStatusError.value = null
      return null
    }
    targetCastStatusLoading.value = true
    targetCastStatusError.value = null
    try {
      const response = await api.get(`/api/cast/targets/${encodeURIComponent(target.id)}/status`)
      targetCastStatus.value = response.data || null
      return targetCastStatus.value
    } catch (error) {
      targetCastStatus.value = null
      targetCastStatusError.value = error
      logger.warn('[RemoteControl] Failed to load cast target status:', error)
      return null
    } finally {
      targetCastStatusLoading.value = false
    }
  }

  function isCommandSupported(command) {
    return supportedCommands.value.includes(command)
  }

  function deviceSessionEndpoint(command) {
    if (command === 'play_media') return 'play-media'
    if (command === 'play_queue') return 'play-queue'
    if (command === 'play_command') return 'playing'
    if (command === 'message') return 'message'
    return 'commands'
  }

  function deviceSessionPayload(command, payload = {}) {
    const fromDeviceId = authStore.deviceId || undefined
    if (command === 'play_media') {
      return {
        media_guid: payload.media_guid,
        media_type: payload.media_type,
        media_title: payload.media_title,
        file_guid: payload.file_guid,
        from_device_id: fromDeviceId,
      }
    }
    if (command === 'play_queue') {
      return {
        items: payload.items || [],
        start_index: payload.start_index ?? 0,
        start_position_seconds: payload.start_position_seconds,
        from_device_id: fromDeviceId,
      }
    }
    if (command === 'play_command') {
      return {
        item_ids: payload.item_ids || [],
        play_command: payload.play_command || 'play_now',
        start_index: payload.start_index,
        start_position_seconds: payload.start_position_seconds,
        media_source_id: payload.media_source_id,
        audio_stream_index: payload.audio_stream_index,
        subtitle_stream_index: payload.subtitle_stream_index,
        from_device_id: fromDeviceId,
      }
    }
    if (command === 'message') {
      return {
        title: payload.title,
        text: payload.text || payload.message || '',
        timeout_seconds: payload.timeout_seconds,
        from_device_id: fromDeviceId,
      }
    }
    return {
      command,
      payload,
      from_device_id: fromDeviceId,
    }
  }

  async function loadTargetSession(device = targetDevice.value) {
    if (!device || isNativeCastTarget(device) || !device.device_id) {
      targetSession.value = null
      targetSessionError.value = null
      return null
    }

    targetSessionLoading.value = true
    targetSessionError.value = null
    try {
      const response = await api.get(
        `/api/devices/by-id/${encodeURIComponent(device.device_id)}/session`,
      )
      const session = response.data || null
      targetSession.value = session
      if (targetDevice.value?.device_id === device.device_id && session?.device) {
        targetDevice.value = { ...targetDevice.value, ...session.device }
      }
      return session
    } catch (error) {
      targetSession.value = null
      targetSessionError.value = error
      logger.error('[RemoteControl] Failed to load target session:', error)
      return null
    } finally {
      targetSessionLoading.value = false
    }
  }

  async function sendDeviceSessionCommand(command, payload = {}) {
    const device = targetDevice.value
    if (!device?.device_id) return false
    try {
      const endpoint = deviceSessionEndpoint(command)
      await api.post(
        `/api/devices/by-id/${encodeURIComponent(device.device_id)}/${endpoint}`,
        deviceSessionPayload(command, payload),
      )
      loadTargetSession(device).catch((error) =>
        logger.warn('[RemoteControl] Target session refresh failed:', error),
      )
      return true
    } catch (error) {
      logger.error('[RemoteControl] Device session command failed:', error)
      return false
    }
  }

  async function sendRemoteCommand(command, payload = {}) {
    if (!targetDevice.value) {
      logger.warn('[RemoteControl] No target device set')
      return false
    }

    if (isNativeCastTarget(targetDevice.value)) {
      return sendCastTargetCommand(command, payload)
    }

    return sendDeviceSessionCommand(command, payload)
  }

  function sendRemoteCommandOverWebSocket(command, payload = {}) {
    if (!targetDevice.value) {
      logger.warn('[RemoteControl] No target device set')
      return false
    }

    // Check if WebSocket is connected
    if (!ws.isConnected.value) {
      logger.error('[RemoteControl] WebSocket not connected!')
      return false
    }

    const message = {
      action: 'remote_control',
      target_device_id: targetDevice.value.device_id,
      command,
      payload,
    }

    logger.debug('[RemoteControl] Sending command:', command)
    logger.debug('[RemoteControl] Target device_id:', targetDevice.value.device_id)
    logger.debug('[RemoteControl] Full message:', JSON.stringify(message))

    const result = ws.send(message)
    logger.debug('[RemoteControl] Send result:', result)
    return result
  }

  // Send play_media command to start a specific media item on remote device
  function sendPlayMediaCommand(mediaType, mediaGuid, mediaTitle, fileGuid = null) {
    return sendRemoteCommand('play_media', {
      media_type: mediaType,
      media_guid: mediaGuid,
      media_title: mediaTitle,
      file_guid: fileGuid,
    })
  }

  function sendPlayCommand(itemIds, options = {}) {
    return sendRemoteCommand('play_command', {
      item_ids: itemIds,
      play_command: options.playCommand || options.play_command || 'play_now',
      start_index: options.startIndex ?? options.start_index,
      start_position_seconds: options.startPositionSeconds ?? options.start_position_seconds,
      media_source_id: options.mediaSourceId || options.media_source_id,
      audio_stream_index: options.audioStreamIndex ?? options.audio_stream_index,
      subtitle_stream_index: options.subtitleStreamIndex ?? options.subtitle_stream_index,
    })
  }

  // Send pause command to remote device
  function sendPauseCommand() {
    return sendRemoteCommand('pause')
  }

  // Send resume command to remote device
  function sendResumeCommand() {
    return sendRemoteCommand('resume')
  }

  // Send stop command to remote device
  function sendStopCommand() {
    return sendRemoteCommand('stop')
  }

  // Send seek command to remote device
  function sendSeekCommand(position) {
    return sendRemoteCommand('seek', { position })
  }

  // Send volume command to remote device
  function sendVolumeCommand(level) {
    return sendRemoteCommand('volume', { level })
  }

  // Send mute toggle command to remote device
  function sendMuteCommand() {
    return sendRemoteCommand('mute')
  }

  function sendMessageCommand({ title = null, text, timeoutSeconds = null } = {}) {
    return sendRemoteCommand('message', {
      title,
      text,
      timeout_seconds: timeoutSeconds,
    })
  }

  // Send next episode/track command to remote device
  function sendNextCommand() {
    return sendRemoteCommand('next')
  }

  // Send previous episode/track command to remote device
  function sendPreviousCommand() {
    return sendRemoteCommand('previous')
  }

  // Send skip forward command to remote device
  function sendSkipForwardCommand(seconds = 10) {
    return sendRemoteCommand('skip_forward', { seconds })
  }

  // Send skip backward command to remote device
  function sendSkipBackwardCommand(seconds = 10) {
    return sendRemoteCommand('skip_backward', { seconds })
  }

  // Clear remote controlled state
  function clearRemoteControlled() {
    isRemoteControlled.value = false
    remoteController.value = null
  }

  return {
    // State
    targetDevice,
    targetSession,
    targetSessionLoading,
    targetSessionError,
    targetCastStatus,
    targetCastStatusLoading,
    targetCastStatusError,
    isRemoteControlled,
    remoteController,

    // Computed
    isControllingRemote,
    hasRemoteTarget,
    targetCapabilities,
    targetNowPlaying,
    targetQueueState,
    supportedCommands,
    supportsVolumeControl,
    supportsQueueControl,
    supportsDisplayMessage,

    // Actions
    setTargetDevice,
    clearTargetDevice,
    isNativeCastTarget,
    playbackProfileForTarget,
    playbackOptionsForTarget,
    loadTargetSession,
    loadCastTargetStatus,
    isCommandSupported,
    sendRemoteCommand,
    sendRemoteCommandOverWebSocket,
    sendCastTargetCommand,
    sendDeviceSessionCommand,
    sendPlayMediaCommand,
    sendPlayCommand,
    sendPauseCommand,
    sendResumeCommand,
    sendStopCommand,
    sendSeekCommand,
    sendVolumeCommand,
    sendMuteCommand,
    sendMessageCommand,
    sendNextCommand,
    sendPreviousCommand,
    sendSkipForwardCommand,
    sendSkipBackwardCommand,
    clearRemoteControlled,
  }
})
