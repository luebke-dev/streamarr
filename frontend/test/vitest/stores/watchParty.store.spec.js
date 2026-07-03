import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockApi = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('boot/axios', () => ({ api: mockApi }))

import { usePartyStore } from 'src/stores/party'

describe('usePartyStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApi.get.mockResolvedValue({ data: {} })
    mockApi.post.mockResolvedValue({ data: {} })
    mockApi.delete.mockResolvedValue({ data: {} })
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('starts with no active party', () => {
      const store = usePartyStore()
      expect(store.activeParty).toBeNull()
    })

    it('starts with empty members list', () => {
      const store = usePartyStore()
      expect(store.members).toEqual([])
    })

    it('starts as not the host', () => {
      const store = usePartyStore()
      expect(store.isHost).toBe(false)
    })

    it('starts disconnected', () => {
      const store = usePartyStore()
      expect(store.isConnected).toBe(false)
    })

    it('starts with default sync state', () => {
      const store = usePartyStore()
      expect(store.syncState).toEqual({
        currentTime: 0,
        isPlaying: false,
        playbackRate: 1.0,
        lastSyncAt: null,
      })
    })
  })

  describe('computed: isInParty', () => {
    it('is false when activeParty is null', () => {
      const store = usePartyStore()
      expect(store.isInParty).toBe(false)
    })

    it('is true when activeParty is set', () => {
      const store = usePartyStore()
      store.activeParty = { guid: 'party-1', party_code: 'ABC123' }
      expect(store.isInParty).toBe(true)
    })
  })

  describe('computed: partyCode', () => {
    it('returns null when no active party', () => {
      const store = usePartyStore()
      expect(store.partyCode).toBeNull()
    })

    it('returns party_code from active party', () => {
      const store = usePartyStore()
      store.activeParty = { guid: 'party-1', party_code: 'XYZ789' }
      expect(store.partyCode).toBe('XYZ789')
    })
  })

  describe('computed: memberCount', () => {
    it('returns 0 for empty members', () => {
      const store = usePartyStore()
      expect(store.memberCount).toBe(0)
    })

    it('returns the correct member count', () => {
      const store = usePartyStore()
      store.members = [
        { user_id: 'u1', is_connected: true },
        { user_id: 'u2', is_connected: false },
      ]
      expect(store.memberCount).toBe(2)
    })
  })

  describe('computed: connectedMembers', () => {
    it('filters to only connected members', () => {
      const store = usePartyStore()
      store.members = [
        { user_id: 'u1', is_connected: true },
        { user_id: 'u2', is_connected: false },
        { user_id: 'u3', is_connected: true },
      ]
      expect(store.connectedMembers).toHaveLength(2)
      expect(store.connectedMembers.every((m) => m.is_connected)).toBe(true)
    })

    it('returns empty array when no members are connected', () => {
      const store = usePartyStore()
      store.members = [{ user_id: 'u1', is_connected: false }]
      expect(store.connectedMembers).toEqual([])
    })
  })

  describe('createParty', () => {
    it('sets activeParty and marks as host on success', async () => {
      const partyData = { guid: 'p-guid', party_code: 'NEW123', members: [] }
      mockApi.post.mockResolvedValue({ data: partyData })

      const store = usePartyStore()
      const result = await store.createParty()

      expect(store.activeParty).toEqual(partyData)
      expect(store.isHost).toBe(true)
      expect(result).toEqual(partyData)
    })

    it('uses response members list', async () => {
      const partyData = {
        guid: 'p-guid',
        party_code: 'NEW123',
        members: [{ user_id: 'host', is_connected: true }],
      }
      mockApi.post.mockResolvedValue({ data: partyData })

      const store = usePartyStore()
      await store.createParty()

      expect(store.members).toEqual(partyData.members)
    })

    it('sends correct payload with name and allow_control', async () => {
      mockApi.post.mockResolvedValue({ data: { party_code: 'X', members: [] } })
      const store = usePartyStore()
      await store.createParty(null, null, { name: 'Movie Night', allowControl: true })

      expect(mockApi.post).toHaveBeenCalledWith('/api/parties', {
        name: 'Movie Night',
        allow_control: true,
      })
    })

    it('includes media_id and media_type when provided', async () => {
      mockApi.post.mockResolvedValue({ data: { party_code: 'X', members: [] } })
      const store = usePartyStore()
      await store.createParty('movie-guid', 'movies')

      const payload = mockApi.post.mock.calls[0][1]
      expect(payload.media_id).toBe('movie-guid')
      expect(payload.media_type).toBe('movies')
    })

    it('rethrows on failure', async () => {
      mockApi.post.mockRejectedValue(new Error('API error'))
      const store = usePartyStore()
      await expect(store.createParty()).rejects.toThrow('API error')
    })
  })

  describe('joinParty', () => {
    it('sets activeParty and isHost: false on success', async () => {
      const partyData = { guid: 'p-guid', party_code: 'JOIN1', members: [] }
      mockApi.post.mockResolvedValue({ data: partyData })

      const store = usePartyStore()
      const result = await store.joinParty('JOIN1')

      expect(store.activeParty).toEqual(partyData)
      expect(store.isHost).toBe(false)
      expect(result).toEqual(partyData)
    })

    it('sends party_code in request body', async () => {
      mockApi.post.mockResolvedValue({ data: { party_code: 'JOIN1', members: [] } })
      const store = usePartyStore()
      await store.joinParty('JOIN1')

      expect(mockApi.post).toHaveBeenCalledWith('/api/parties/join', {
        party_code: 'JOIN1',
      })
    })

    it('rethrows on failure', async () => {
      mockApi.post.mockRejectedValue({ response: { data: { detail: 'Party not found' } } })
      const store = usePartyStore()
      await expect(store.joinParty('INVALID')).rejects.toBeTruthy()
    })
  })

  describe('leaveParty', () => {
    it('does nothing when no active party', async () => {
      const store = usePartyStore()
      await store.leaveParty()
      expect(mockApi.delete).not.toHaveBeenCalled()
    })

    it('calls DELETE leave endpoint and resets state', async () => {
      const store = usePartyStore()
      store.activeParty = { guid: 'p-guid', party_code: 'X' }
      store.members = [{ user_id: 'u1' }]
      store.isHost = true

      await store.leaveParty()

      expect(mockApi.delete).toHaveBeenCalledWith('/api/parties/p-guid/leave')
      expect(store.activeParty).toBeNull()
      expect(store.members).toEqual([])
      expect(store.isHost).toBe(false)
    })

    it('resets state even when API call fails', async () => {
      mockApi.delete.mockRejectedValue(new Error('Network error'))
      const store = usePartyStore()
      store.activeParty = { guid: 'p-guid' }

      await store.leaveParty()

      expect(store.activeParty).toBeNull()
    })
  })

  describe('addMember', () => {
    it('adds a new member to the list', () => {
      const store = usePartyStore()
      const member = { user_id: 'u1', username: 'Alice', is_connected: true }
      store.addMember(member)
      expect(store.members).toContainEqual(member)
    })

    it('updates an existing member instead of duplicating', () => {
      const store = usePartyStore()
      store.members = [{ user_id: 'u1', username: 'Alice', is_connected: false }]
      store.addMember({ user_id: 'u1', username: 'Alice', is_connected: true })
      expect(store.members).toHaveLength(1)
      expect(store.members[0].is_connected).toBe(true)
    })
  })

  describe('removeMember', () => {
    it('removes the member with the given userId', () => {
      const store = usePartyStore()
      store.members = [{ user_id: 'u1' }, { user_id: 'u2' }]
      store.removeMember('u1')
      expect(store.members).toHaveLength(1)
      expect(store.members[0].user_id).toBe('u2')
    })

    it('does nothing when userId is not found', () => {
      const store = usePartyStore()
      store.members = [{ user_id: 'u1' }]
      store.removeMember('u99')
      expect(store.members).toHaveLength(1)
    })
  })

  describe('updateMemberStatus', () => {
    it('merges updates into the matching member', () => {
      const store = usePartyStore()
      store.members = [{ user_id: 'u1', is_connected: false, current_time: 0 }]
      store.updateMemberStatus('u1', { is_connected: true, current_time: 42 })
      expect(store.members[0]).toMatchObject({ is_connected: true, current_time: 42 })
    })

    it('does nothing when userId is not found', () => {
      const store = usePartyStore()
      store.members = [{ user_id: 'u1', is_connected: false }]
      store.updateMemberStatus('u99', { is_connected: true })
      expect(store.members[0].is_connected).toBe(false)
    })
  })

  describe('updateSyncState', () => {
    it('updates syncState from data object', () => {
      const store = usePartyStore()
      store.updateSyncState({ current_time: 123, is_playing: true, playback_rate: 1.5 })
      expect(store.syncState.currentTime).toBe(123)
      expect(store.syncState.isPlaying).toBe(true)
      expect(store.syncState.playbackRate).toBe(1.5)
      expect(store.syncState.lastSyncAt).toBeInstanceOf(Date)
    })

    it('defaults playbackRate to 1.0 when not provided', () => {
      const store = usePartyStore()
      store.updateSyncState({ current_time: 0, is_playing: false })
      expect(store.syncState.playbackRate).toBe(1.0)
    })
  })

  describe('resetState', () => {
    it('clears all state to defaults', () => {
      const store = usePartyStore()
      store.activeParty = { guid: 'p-guid' }
      store.members = [{ user_id: 'u1' }]
      store.isHost = true
      store.isConnected = true

      store.resetState()

      expect(store.activeParty).toBeNull()
      expect(store.members).toEqual([])
      expect(store.isHost).toBe(false)
      expect(store.isConnected).toBe(false)
      expect(store.syncState).toEqual({
        currentTime: 0,
        isPlaying: false,
        playbackRate: 1.0,
        lastSyncAt: null,
      })
    })
  })

  describe('syncPlayback', () => {
    it('does nothing when no active party', async () => {
      const store = usePartyStore()
      await store.syncPlayback(100, true)
      expect(mockApi.post).not.toHaveBeenCalled()
    })

    it('posts to sync endpoint and updates local syncState', async () => {
      const store = usePartyStore()
      store.activeParty = { guid: 'p-guid' }

      await store.syncPlayback(120, true, 1.25)

      expect(mockApi.post).toHaveBeenCalledWith('/api/parties/p-guid/sync', {
        current_time: 120,
        is_playing: true,
        playback_rate: 1.25,
      })
      expect(store.syncState.currentTime).toBe(120)
      expect(store.syncState.isPlaying).toBe(true)
      expect(store.syncState.playbackRate).toBe(1.25)
    })
  })

  describe('fetchMyParties', () => {
    it('calls GET /api/parties and returns data', async () => {
      const parties = [{ guid: 'p1' }]
      mockApi.get.mockResolvedValue({ data: parties })
      const store = usePartyStore()
      const result = await store.fetchMyParties()
      expect(mockApi.get).toHaveBeenCalledWith('/api/parties')
      expect(result).toEqual(parties)
    })

    it('returns empty array on error', async () => {
      mockApi.get.mockRejectedValue(new Error('Network error'))
      const store = usePartyStore()
      const result = await store.fetchMyParties()
      expect(result).toEqual([])
    })
  })
})
