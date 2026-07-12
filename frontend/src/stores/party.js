import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

export const usePartyStore = defineStore('watchParty', () => {
  // State
  const activeParty = ref(null)
  const members = ref([])
  const isHost = ref(false)
  const isConnected = ref(false)
  const syncState = ref({
    currentTime: 0,
    isPlaying: false,
    playbackRate: 1.0,
    lastSyncAt: null,
  })

  // Computed
  const isInParty = computed(() => activeParty.value !== null)
  const partyCode = computed(() => activeParty.value?.party_code || null)
  const memberCount = computed(() => members.value.length)
  const connectedMembers = computed(() => members.value.filter((m) => m.is_connected))

  // Actions
  async function createParty(mediaId = null, mediaType = null, options = {}) {
    try {
      const payload = {
        name: options.name || null,
        allow_control: options.allowControl || false,
      }

      // Add media info only if provided
      if (mediaId && mediaType) {
        payload.media_id = mediaId
        payload.media_type = mediaType
      }

      const response = await api.post('/api/parties', payload)

      activeParty.value = response.data
      members.value = response.data.members || []
      isHost.value = true

      return response.data
    } catch (error) {
      logger.error('Failed to create party:', error)
      throw error
    }
  }

  async function joinParty(partyCode) {
    try {
      const response = await api.post('/api/parties/join', {
        party_code: partyCode,
      })

      activeParty.value = response.data
      members.value = response.data.members || []
      isHost.value = false

      return response.data
    } catch (error) {
      logger.error('Failed to join party:', error)
      throw error
    }
  }

  async function leaveParty() {
    if (!activeParty.value) return

    try {
      await api.delete(`/api/parties/${activeParty.value.guid}/leave`)

      resetState()
    } catch (error) {
      logger.error('Failed to leave party:', error)
      // Reset state anyway
      resetState()
    }
  }

  async function endParty() {
    if (!activeParty.value || !isHost.value) return

    try {
      await api.delete(`/api/parties/${activeParty.value.guid}`)

      resetState()
    } catch (error) {
      logger.error('Failed to end party:', error)
    }
  }

  async function sendHeartbeat() {
    if (!activeParty.value) return

    try {
      await api.post(`/api/parties/${activeParty.value.guid}/heartbeat`)
    } catch (error) {
      logger.error('Failed to send heartbeat:', error)
      // If heartbeat fails, we might be disconnected
      if (error.response?.status === 404 || error.response?.status === 403) {
        resetState()
      }
    }
  }

  async function fetchPartyDetails() {
    if (!activeParty.value) return

    try {
      const response = await api.get(`/api/parties/${activeParty.value.guid}`)
      activeParty.value = response.data
      members.value = response.data.members || []

      // Update sync state from server
      syncState.value = {
        currentTime: response.data.current_time,
        isPlaying: response.data.is_playing,
        playbackRate: response.data.playback_rate,
        lastSyncAt: new Date(response.data.last_sync_at),
      }
    } catch (error) {
      logger.error('Failed to fetch party details:', error)
      if (error.response?.status === 404) {
        resetState()
      }
    }
  }

  async function fetchMyParties() {
    try {
      const response = await api.get('/api/parties')
      return response.data
    } catch (error) {
      logger.error('Failed to fetch my parties:', error)
      return []
    }
  }

  async function fetchFriendsParties() {
    try {
      const response = await api.get('/api/parties/friends')
      return response.data
    } catch (error) {
      logger.error('Failed to fetch friends parties:', error)
      return []
    }
  }

  async function kickMember(userId) {
    if (!activeParty.value || !isHost.value) return

    try {
      await api.delete(`/api/parties/${activeParty.value.guid}/members/${userId}`)
      members.value = members.value.filter((m) => m.user_id !== userId)
    } catch (error) {
      logger.error('Failed to kick member:', error)
    }
  }

  function updateMemberStatus(userId, updates) {
    const memberIndex = members.value.findIndex((m) => m.user_id === userId)
    if (memberIndex !== -1) {
      members.value[memberIndex] = {
        ...members.value[memberIndex],
        ...updates,
      }
    }
  }

  function addMember(member) {
    const existingIndex = members.value.findIndex((m) => m.user_id === member.user_id)
    if (existingIndex === -1) {
      members.value.push(member)
    } else {
      members.value[existingIndex] = member
    }
  }

  function removeMember(userId) {
    members.value = members.value.filter((m) => m.user_id !== userId)
  }

  function updateSyncState(data) {
    syncState.value = {
      currentTime: data.current_time,
      isPlaying: data.is_playing,
      playbackRate: data.playback_rate || 1.0,
      lastSyncAt: new Date(),
    }
  }

  function resetState() {
    activeParty.value = null
    members.value = []
    isHost.value = false
    isConnected.value = false
    syncState.value = {
      currentTime: 0,
      isPlaying: false,
      playbackRate: 1.0,
      lastSyncAt: null,
    }
  }

  // Start heartbeat interval when party is active
  let heartbeatInterval = null
  function startHeartbeat() {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval)
    }
    // Send heartbeat every 30 seconds
    heartbeatInterval = setInterval(() => {
      if (isInParty.value) {
        sendHeartbeat()
      }
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval)
      heartbeatInterval = null
    }
  }

  return {
    // State
    activeParty,
    members,
    isHost,
    isConnected,
    syncState,

    // Computed
    isInParty,
    partyCode,
    memberCount,
    connectedMembers,

    // Actions
    createParty,
    joinParty,
    leaveParty,
    endParty,
    sendHeartbeat,
    fetchPartyDetails,
    fetchMyParties,
    fetchFriendsParties,
    updateMemberStatus,
    addMember,
    kickMember,
    removeMember,
    updateSyncState,
    resetState,
    startHeartbeat,
    stopHeartbeat,
  }
})
