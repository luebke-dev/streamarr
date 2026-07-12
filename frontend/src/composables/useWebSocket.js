/**
 * WebSocket composable for real-time updates.
 *
 * Provides a persistent WebSocket connection to the backend with
 * automatic reconnection and subscription management.
 */

import { ref, computed } from 'vue'
import { getAccessToken, getServerUrl } from 'src/utils/authStorage'
import { getStoredDeviceId } from 'src/utils/deviceIdentity'
import { logger } from 'src/utils/logger'

// Connection states
const ConnectionState = {
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
}

// Singleton WebSocket instance for the app
let globalSocket = null
let globalState = ref(ConnectionState.DISCONNECTED)
let reconnectAttempts = 0
let reconnectTimeout = null
let heartbeatInterval = null
let statusUpdateInterval = null
// True while we're parked waiting for a network/visibility event to resume
// after exhausting the reconnect budget — prevents stacking listeners.
let resumeListenersRegistered = false
// Holds the exact listener refs so we can detach them again.
let resumeHandlers = null
const MAX_RECONNECT_ATTEMPTS = 10
const RECONNECT_DELAY_BASE = 1000 // Start with 1 second
const HEARTBEAT_INTERVAL = 30000 // 30 seconds
const STATUS_UPDATE_INTERVAL = 5000 // 5 seconds

// Event handlers by channel
const eventHandlers = new Map()

// Global event handlers (for all events regardless of channel)
const globalEventHandlers = new Map()

// Lifecycle listeners fired *after* a reconnect re-opens the socket. Lets
// components refetch their REST state so events that dropped during the gap
// are reconciled without a custom replay protocol.
const reconnectListeners = new Set()

// True once we've been connected at least once this session — used to
// distinguish "first connect" (no refetch needed) from "reconnect".
let hasEverConnected = false

// Current playback state (updated by PlayPage)
const currentPlayback = ref({
  isPlaying: false,
  mediaType: null,
  mediaGuid: null,
  mediaTitle: null,
  position: 0,
  duration: 0,
})

/**
 * Get the WebSocket URL from the stored server URL (same source as axios baseURL).
 */
function getWebSocketUrl() {
  const token = getAccessToken()
  const deviceId = getStoredDeviceId()

  // Derive host + protocol from the stored server URL (set on the login page),
  // falling back to the current page origin for same-origin / dev-proxy setups.
  const serverUrl = getServerUrl()
  let protocol, host
  if (serverUrl) {
    try {
      const parsed = new URL(serverUrl)
      protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
      host = parsed.host
    } catch (e) {
      // Invalid serverUrl; fall back to current window location for WS
      logger.warn('Invalid WS server URL, falling back to window.location', e)
      protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      host = window.location.host
    }
  } else {
    protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    host = window.location.host
  }

  let url = `${protocol}//${host}/api/ws?token=${encodeURIComponent(token)}`
  if (deviceId) {
    url += `&device_id=${encodeURIComponent(deviceId)}`
  }
  return url
}

/**
 * Build a copy of the WS URL with the token redacted, safe for logging.
 * The raw token must never reach logs/consoles/screenshares.
 */
function redactWebSocketUrl(url) {
  return url.replace(/([?&]token=)[^&]*/i, '$1<redacted>')
}

/**
 * Connect to the WebSocket server.
 */
function connect() {
  if (globalSocket?.readyState === WebSocket.OPEN) {
    return
  }

  if (globalSocket?.readyState === WebSocket.CONNECTING) {
    return
  }

  const token = getAccessToken()
  if (!token) {
    logger.warn('[WebSocket] No auth token available')
    return
  }

  globalState.value = ConnectionState.CONNECTING
  const wsUrl = getWebSocketUrl()

  logger.debug('[WebSocket] Connecting to:', redactWebSocketUrl(wsUrl))

  try {
    globalSocket = new WebSocket(wsUrl)

    globalSocket.onopen = () => {
      logger.debug('[WebSocket] Connected')
      const wasReconnect = hasEverConnected
      globalState.value = ConnectionState.CONNECTED
      reconnectAttempts = 0
      hasEverConnected = true
      removeResumeListeners()

      startHeartbeat()
      startStatusUpdateInterval()
      resubscribeAll()

      // Second and later connects: fire lifecycle listeners so components
      // can re-fetch their current state (party-sync position, availability,
      // files list, etc.). Events that landed during the disconnect gap are
      // not replayed; the refetch is the reconciliation.
      if (wasReconnect) {
        logger.debug('[WebSocket] Reconnected — firing %d listener(s)', reconnectListeners.size)
        for (const fn of reconnectListeners) {
          try {
            fn()
          } catch (e) {
            logger.error('[WebSocket] reconnect listener threw:', e)
          }
        }
      }
    }

    globalSocket.onclose = (event) => {
      logger.debug('[WebSocket] Closed:', event.code, event.reason)
      globalState.value = ConnectionState.DISCONNECTED
      stopHeartbeat()
      stopStatusUpdateInterval()

      // Attempt reconnection unless it was a clean close
      if (event.code !== 1000 && event.code !== 4001 && event.code !== 4003) {
        scheduleReconnect()
      }
    }

    globalSocket.onerror = (error) => {
      logger.error('[WebSocket] Error:', error)
    }

    globalSocket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)
        handleMessage(message)
      } catch (e) {
        logger.error('[WebSocket] Failed to parse message:', e)
      }
    }
  } catch (error) {
    logger.error('[WebSocket] Failed to create connection:', error)
    globalState.value = ConnectionState.DISCONNECTED
    scheduleReconnect()
  }
}

/**
 * Disconnect from the WebSocket server.
 */
function disconnect({ clearHandlers = true } = {}) {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout)
    reconnectTimeout = null
  }

  stopHeartbeat()
  stopStatusUpdateInterval()
  removeResumeListeners()

  if (globalSocket) {
    globalSocket.close(1000, 'Client disconnect')
    globalSocket = null
  }

  if (clearHandlers) {
    // Clear all event handlers to prevent memory leaks
    eventHandlers.clear()
    globalEventHandlers.clear()
    reconnectListeners.clear()
    hasEverConnected = false
  }

  globalState.value = ConnectionState.DISCONNECTED
  reconnectAttempts = 0
}

/**
 * Register a callback fired after a successful reconnect. Use this from
 * components that need to refetch REST state once the socket is back up —
 * events missed during the disconnect gap are not replayed. Returns an
 * unsubscribe function; caller is responsible for calling it on unmount.
 */
function onReconnected(handler) {
  reconnectListeners.add(handler)
  return () => reconnectListeners.delete(handler)
}

function offReconnected(handler) {
  reconnectListeners.delete(handler)
}

/**
 * Schedule a reconnection attempt.
 */
function scheduleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    logger.error('[WebSocket] Max reconnect attempts reached — parking until network/visibility resumes')
    registerResumeListeners()
    return
  }

  globalState.value = ConnectionState.RECONNECTING
  reconnectAttempts++

  // Exponential backoff with jitter
  const delay =
    Math.min(RECONNECT_DELAY_BASE * Math.pow(2, reconnectAttempts - 1), 30000) +
    Math.random() * 1000

  logger.debug(`[WebSocket] Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts})`)

  reconnectTimeout = setTimeout(() => {
    connect()
  }, delay)
}

/**
 * Once the reconnect budget is exhausted we stop the exponential-backoff
 * loop, but we must not stay dead forever: a laptop that slept or lost wifi
 * for a few minutes should recover on wake. Register one-shot listeners that
 * reset the attempt counter and reconnect when the browser signals the
 * network is back (`online`) or the tab becomes visible/focused again.
 */
function registerResumeListeners() {
  if (resumeListenersRegistered || typeof window === 'undefined') {
    return
  }
  resumeListenersRegistered = true

  const resume = () => {
    // Only resume if we're still meant to be connected (have a token) and
    // aren't already re-establishing.
    if (globalSocket?.readyState === WebSocket.OPEN || globalSocket?.readyState === WebSocket.CONNECTING) {
      removeResumeListeners()
      return
    }
    if (!getAccessToken()) {
      return
    }
    logger.debug('[WebSocket] Resume signal received — retrying connection')
    removeResumeListeners()
    reconnectAttempts = 0
    connect()
  }

  const onVisibility = () => {
    if (document.visibilityState === 'visible') {
      resume()
    }
  }

  // Stash the handlers so removeResumeListeners can detach the exact refs.
  resumeHandlers = { resume, onVisibility }
  window.addEventListener('online', resume)
  window.addEventListener('focus', resume)
  document.addEventListener('visibilitychange', onVisibility)
}

function removeResumeListeners() {
  if (!resumeListenersRegistered || typeof window === 'undefined') {
    return
  }
  resumeListenersRegistered = false
  if (resumeHandlers) {
    window.removeEventListener('online', resumeHandlers.resume)
    window.removeEventListener('focus', resumeHandlers.resume)
    document.removeEventListener('visibilitychange', resumeHandlers.onVisibility)
    resumeHandlers = null
  }
}

/**
 * Send current device/playback status to the server.
 */
function sendDeviceStatus() {
  const deviceId = getStoredDeviceId()
  return send({
    action: 'device_status',
    device_id: deviceId,
    is_playing: currentPlayback.value.isPlaying,
    media_type: currentPlayback.value.mediaType,
    media_guid: currentPlayback.value.mediaGuid,
    media_title: currentPlayback.value.mediaTitle,
    position: Math.floor(currentPlayback.value.position),
    duration: Math.floor(currentPlayback.value.duration),
  })
}

/**
 * Update playback status and immediately push it to the server.
 */
function updatePlaybackStatus(status) {
  currentPlayback.value = {
    isPlaying: status.isPlaying ?? false,
    mediaType: status.mediaType ?? null,
    mediaGuid: status.mediaGuid ?? null,
    mediaTitle: status.mediaTitle ?? null,
    position: status.position ?? 0,
    duration: status.duration ?? 0,
  }
  if (globalSocket?.readyState === WebSocket.OPEN) {
    sendDeviceStatus()
  }
}

/**
 * Clear playback status (when playback stops).
 */
function clearPlaybackStatus() {
  currentPlayback.value = {
    isPlaying: false,
    mediaType: null,
    mediaGuid: null,
    mediaTitle: null,
    position: 0,
    duration: 0,
  }
  if (globalSocket?.readyState === WebSocket.OPEN) {
    sendDeviceStatus()
  }
}

/**
 * Start periodic device status updates.
 */
function startStatusUpdateInterval() {
  stopStatusUpdateInterval()
  statusUpdateInterval = setInterval(() => {
    sendDeviceStatus()
  }, STATUS_UPDATE_INTERVAL)
}

/**
 * Stop periodic device status updates.
 */
function stopStatusUpdateInterval() {
  if (statusUpdateInterval) {
    clearInterval(statusUpdateInterval)
    statusUpdateInterval = null
  }
}

/**
 * Register a handler for a specific event type (global, not channel-scoped).
 * Returns an unsubscribe function.
 */
function on(eventType, handler) {
  onGlobalEvent(eventType, handler)
  return () => off(eventType, handler)
}

/**
 * Remove a previously registered global event handler.
 */
function off(eventType, handler) {
  offGlobalEvent(eventType, handler)
}

/**
 * Start the heartbeat interval.
 */
function startHeartbeat() {
  stopHeartbeat()
  heartbeatInterval = setInterval(() => {
    if (globalSocket?.readyState === WebSocket.OPEN) {
      send({ action: 'ping' })
    }
  }, HEARTBEAT_INTERVAL)
}

/**
 * Stop the heartbeat interval.
 */
function stopHeartbeat() {
  if (heartbeatInterval) {
    clearInterval(heartbeatInterval)
    heartbeatInterval = null
  }
}

/**
 * Send a message to the server.
 */
function send(message) {
  if (globalSocket?.readyState === WebSocket.OPEN) {
    globalSocket.send(JSON.stringify(message))
    return true
  }
  logger.warn('[WebSocket] Cannot send, not connected')
  return false
}

/**
 * Handle an incoming message from the server.
 */
function handleMessage(message) {
  const { event, data } = message

  logger.debug('[WebSocket] Received:', event, data)

  // Trigger global handlers for this event type
  const globalHandlersForEvent = globalEventHandlers.get(event)
  if (globalHandlersForEvent) {
    globalHandlersForEvent.forEach((handler) => {
      try {
        handler(data)
      } catch (e) {
        logger.error('[WebSocket] Global handler error:', e)
      }
    })
  }

  // For subscribed events, route to channel handlers
  if (event === 'releases_updated' || event === 'files_updated' || event === 'media_available') {
    let channelKey = null

    // New unified media system - check for media_item_id first
    if (data.media_item_id) {
      channelKey = `media_item:${data.media_item_id}`
    }
    // Legacy: Check for episode_id or movie_id for backwards compatibility
    else if (data.episode_id) {
      channelKey = `episode:${data.episode_id}`
    } else if (data.movie_id) {
      channelKey = `movie:${data.movie_id}`
    }

    if (channelKey) {
      const handlers = eventHandlers.get(channelKey)
      if (handlers) {
        handlers.forEach((handler) => {
          try {
            handler(event, data)
          } catch (e) {
            logger.error('[WebSocket] Channel handler error:', e)
          }
        })
      }
    }
  }

  // Handle watch party events
  if (
    event === 'party_sync' ||
    event === 'party_member_update' ||
    event === 'party_member_kicked' ||
    event === 'party_sync_requested' ||
    event === 'party_media_changed'
  ) {
    const channelKey = `party:${data.party_id}`
    const handlers = eventHandlers.get(channelKey)
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(event, data)
        } catch (e) {
          logger.error('[WebSocket] Watch party handler error:', e)
        }
      })
    }
  }
}

/**
 * Re-subscribe to all channels after reconnection.
 */
function resubscribeAll() {
  for (const channelKey of eventHandlers.keys()) {
    const [resourceType, resourceId] = channelKey.split(':')
    send({
      action: 'subscribe',
      resource_type: resourceType,
      resource_id: resourceId,
    })
  }
}

/**
 * Subscribe to events for a specific resource.
 */
function subscribe(resourceType, resourceId, handler) {
  // Ensure we have a primitive value, not a Vue reactive object
  const resolvedId =
    typeof resourceId === 'object' && resourceId !== null && 'value' in resourceId
      ? resourceId.value
      : resourceId

  if (!resolvedId) {
    logger.warn('[WebSocket] Cannot subscribe: resourceId is empty')
    return
  }

  const channelKey = `${resourceType}:${resolvedId}`

  if (!eventHandlers.has(channelKey)) {
    eventHandlers.set(channelKey, new Set())

    // Send subscribe message if connected
    if (globalSocket?.readyState === WebSocket.OPEN) {
      send({
        action: 'subscribe',
        resource_type: resourceType,
        resource_id: String(resolvedId),
      })
    }
  }

  eventHandlers.get(channelKey).add(handler)

  logger.debug('[WebSocket] Subscribed to:', channelKey)
}

/**
 * Unsubscribe from events for a specific resource.
 */
function unsubscribe(resourceType, resourceId, handler) {
  // Ensure we have a primitive value, not a Vue reactive object
  const resolvedId =
    typeof resourceId === 'object' && resourceId !== null && 'value' in resourceId
      ? resourceId.value
      : resourceId

  if (!resolvedId) {
    return
  }

  const channelKey = `${resourceType}:${resolvedId}`

  const handlers = eventHandlers.get(channelKey)
  if (handlers) {
    handlers.delete(handler)

    if (handlers.size === 0) {
      eventHandlers.delete(channelKey)

      // Send unsubscribe message if connected
      if (globalSocket?.readyState === WebSocket.OPEN) {
        send({
          action: 'unsubscribe',
          resource_type: resourceType,
          resource_id: String(resolvedId),
        })
      }
    }
  }

  logger.debug('[WebSocket] Unsubscribed from:', channelKey)
}

/**
 * Add a global event handler for all events of a specific type.
 */
function onGlobalEvent(eventType, handler) {
  if (!globalEventHandlers.has(eventType)) {
    globalEventHandlers.set(eventType, new Set())
  }
  globalEventHandlers.get(eventType).add(handler)
}

/**
 * Remove a global event handler.
 */
function offGlobalEvent(eventType, handler) {
  const handlers = globalEventHandlers.get(eventType)
  if (handlers) {
    handlers.delete(handler)
    if (handlers.size === 0) {
      globalEventHandlers.delete(eventType)
    }
  }
}

/**
 * Send watch party playback sync event.
 */
function sendWatchPartySync(partyId, currentTime, isPlaying, playbackRate = 1.0) {
  return send({
    action: 'party_sync',
    party_id: partyId,
    current_time: currentTime,
    is_playing: isPlaying,
    playback_rate: playbackRate,
  })
}

/**
 * Send watch party member update event.
 */
function sendWatchPartyMemberUpdate(partyId, lastPosition, isConnected = true) {
  return send({
    action: 'party_member_update',
    party_id: partyId,
    last_position: lastPosition,
    is_connected: isConnected,
  })
}

/**
 * Vue composable for WebSocket functionality.
 */
export function useWebSocket() {
  const isConnected = computed(() => globalState.value === ConnectionState.CONNECTED)
  const connectionState = computed(() => globalState.value)

  return {
    // State
    isConnected,
    connectionState,
    ConnectionState,
    currentPlayback,

    // Methods
    connect,
    disconnect,
    send,
    subscribe,
    unsubscribe,
    on,
    off,
    onGlobalEvent,
    offGlobalEvent,
    onReconnected,
    offReconnected,
    sendDeviceStatus,
    updatePlaybackStatus,
    clearPlaybackStatus,
    sendWatchPartySync,
    sendWatchPartyMemberUpdate,
  }
}
