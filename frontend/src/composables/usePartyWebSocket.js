/**
 * Watch Party WebSocket composable.
 *
 * Handles real-time synchronization for watch parties including
 * playback state, member updates, and automatic subscription management.
 */

import { onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useWebSocket } from './useWebSocket'
import { usePartyStore } from 'stores/party'
import { useAuthStore } from 'stores/auth'
import { logger } from 'src/utils/logger'

export function usePartyWebSocket() {
  const ws = useWebSocket()
  const partyStore = usePartyStore()
  const authStore = useAuthStore()
  const router = useRouter()
  let isSubscribed = false
  let onSyncRequestedCallback = null

  /**
   * Handle watch party sync events from other members.
   */
  function handlePartySync(event, data) {
    logger.debug('[WatchParty] Received sync:', data)

    // Don't apply sync from ourselves
    const currentUserId = authStore.user?.guid
    if (data.from_user_id === currentUserId) {
      return
    }

    // Update sync state in store
    partyStore.updateSyncState({
      current_time: data.current_time,
      is_playing: data.is_playing,
      playback_rate: data.playback_rate || 1.0,
    })
  }

  /**
   * Handle watch party member update events.
   */
  function handlePartyMemberUpdate(event, data) {
    logger.debug('[WatchParty] Member update:', data)

    if (data.user_id) {
      partyStore.updateMemberStatus(data.user_id, {
        last_position: data.last_position,
        is_connected: data.is_connected,
        last_heartbeat: new Date(),
      })
    }
  }

  /**
   * Handle sync request from a late joiner — only the host responds.
   */
  function handlePartySyncRequested(event, data) {
    logger.debug('[WatchParty] Sync requested:', data)

    // Only the host responds to avoid duplicate syncs
    if (!partyStore.isHost) return

    const currentUserId = authStore.user?.guid
    if (data.requesting_user_id === currentUserId) return

    if (onSyncRequestedCallback) {
      onSyncRequestedCallback()
    }
  }

  /**
   * Handle media change events — navigate participants to the new content.
   */
  function handlePartyMediaChanged(event, data) {
    logger.debug('[WatchParty] Media changed:', data)

    const currentUserId = authStore.user?.guid
    if (data.from_user_id === currentUserId) return

    if (data.media_id && data.media_type) {
      logger.info('[WatchParty] Navigating to new media:', data.media_id)
      router.push(`/play/${data.media_id}?type=${data.media_type}`)
    }
  }

  /**
   * Handle watch party member kicked events.
   */
  function handlePartyMemberKicked(event, data) {
    logger.debug('[WatchParty] Member kicked:', data)

    const currentUserId = authStore.user?.guid

    if (data.kicked_user_id === currentUserId) {
      // We were kicked - reset state
      partyStore.resetState()
    } else {
      // Someone else was kicked - remove from member list
      partyStore.removeMember(data.kicked_user_id)
    }
  }

  // Stored so subscribe and unsubscribe pass the same function reference;
  // otherwise the WS layer can't find the listener to remove.
  let partyEventHandler = null

  /**
   * Subscribe to watch party events.
   */
  function subscribe(partyId) {
    if (!partyId || isSubscribed) return

    logger.debug('[WatchParty] Subscribing to party:', partyId)

    partyEventHandler = (event, data) => {
      if (event === 'party_sync') {
        handlePartySync(event, data)
      } else if (event === 'party_member_update') {
        handlePartyMemberUpdate(event, data)
      } else if (event === 'party_member_kicked') {
        handlePartyMemberKicked(event, data)
      } else if (event === 'party_sync_requested') {
        handlePartySyncRequested(event, data)
      } else if (event === 'party_media_changed') {
        handlePartyMediaChanged(event, data)
      }
    }

    ws.subscribe('party', partyId, partyEventHandler)

    isSubscribed = true
    partyStore.isConnected = true
  }

  /**
   * Unsubscribe from watch party events.
   */
  function unsubscribe(partyId) {
    if (!partyId || !isSubscribed) return

    logger.debug('[WatchParty] Unsubscribing from party:', partyId)

    if (partyEventHandler) {
      ws.unsubscribe('party', partyId, partyEventHandler)
      partyEventHandler = null
    }

    isSubscribed = false
    partyStore.isConnected = false
  }

  /**
   * Send playback sync to all party members.
   */
  function syncPlayback(currentTime, isPlaying, playbackRate = 1.0) {
    if (!partyStore.activeParty?.guid) {
      logger.warn('[WatchParty] Cannot sync: no active party')
      return false
    }

    return ws.sendWatchPartySync(partyStore.activeParty.guid, currentTime, isPlaying, playbackRate)
  }

  /**
   * Request sync from the host (used by late joiners).
   */
  function requestSync() {
    if (!partyStore.activeParty?.guid) {
      logger.warn('[WatchParty] Cannot request sync: no active party')
      return false
    }

    return ws.send({
      action: 'party_request_sync',
      party_id: partyStore.activeParty.guid,
    })
  }

  /**
   * Register callback for when a sync is requested (host responds with current state).
   */
  function onSyncRequested(callback) {
    onSyncRequestedCallback = callback
  }

  /**
   * Send member update (position/status).
   */
  function updateMemberStatus(lastPosition, isConnected = true) {
    if (!partyStore.activeParty?.guid) {
      return false
    }

    return ws.sendWatchPartyMemberUpdate(partyStore.activeParty.guid, lastPosition, isConnected)
  }

  /**
   * After a WS reconnect, resubscribeAll() in useWebSocket re-sends the
   * subscribe frame, but the host may have sent a sync while we were gone.
   * Ask the host for the current state so our timeline snaps back.
   */
  function handleReconnect() {
    if (partyStore.activeParty?.guid && isSubscribed) {
      logger.debug('[WatchParty] Reconnected — re-requesting host sync')
      requestSync()
      updateMemberStatus(partyStore.syncState?.currentTime ?? 0, true)
    }
  }

  let stopReconnectListener = null

  /**
   * Initialize watch party WebSocket integration.
   * Automatically subscribes/unsubscribes based on active party.
   */
  function initialize() {
    // Auto-subscribe when party becomes active
    watch(
      () => partyStore.activeParty?.guid,
      (newPartyId, oldPartyId) => {
        if (oldPartyId && oldPartyId !== newPartyId) {
          unsubscribe(oldPartyId)
        }

        if (newPartyId) {
          subscribe(newPartyId)
          partyStore.startHeartbeat()
        } else {
          partyStore.stopHeartbeat()
        }
      },
      { immediate: true },
    )

    stopReconnectListener = ws.onReconnected(handleReconnect)
  }

  // Cleanup on unmount
  onUnmounted(() => {
    if (partyStore.activeParty?.guid) {
      unsubscribe(partyStore.activeParty.guid)
    }
    partyStore.stopHeartbeat()
    if (stopReconnectListener) {
      stopReconnectListener()
      stopReconnectListener = null
    }
  })

  return {
    // State
    isConnected: ws.isConnected,
    connectionState: ws.connectionState,

    // Methods
    subscribe,
    unsubscribe,
    syncPlayback,
    requestSync,
    onSyncRequested,
    updateMemberStatus,
    initialize,
  }
}
