import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock WebSocket composable — must be hoisted so the store captures the mock at creation
const mockWs = vi.hoisted(() => ({
  isConnected: { value: false },
  send: vi.fn(),
  on: vi.fn(),
}))

vi.mock('composables/useWebSocket', () => ({
  useWebSocket: () => mockWs,
}))

// Mock auth store
const mockAuthStore = vi.hoisted(() => ({
  user: null,
}))

vi.mock('stores/auth', () => ({
  useAuthStore: () => mockAuthStore,
}))

vi.mock('boot/axios', () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('quasar/wrappers', () => ({
  boot: (fn) => fn,
}))

import { api } from 'boot/axios'
import { useRemoteControlStore } from 'src/stores/remoteControl'
import bootRemoteControl from 'src/boot/remoteControl'

describe('useRemoteControlStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockWs.isConnected.value = false
    mockWs.send.mockReturnValue(true)
    api.post.mockResolvedValue({ data: {} })
    api.get.mockResolvedValue({ data: { device: { device_id: 'x' }, capabilities: {} } })
    mockAuthStore.deviceId = 'controller-device'
    mockAuthStore.user = null
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('has no target device', () => {
      const store = useRemoteControlStore()
      expect(store.targetDevice).toBeNull()
    })

    it('is not remote controlled', () => {
      const store = useRemoteControlStore()
      expect(store.isRemoteControlled).toBe(false)
    })

    it('has no remote controller', () => {
      const store = useRemoteControlStore()
      expect(store.remoteController).toBeNull()
    })
  })

  describe('computed: isControllingRemote / hasRemoteTarget', () => {
    it('isControllingRemote is false when no target device', () => {
      const store = useRemoteControlStore()
      expect(store.isControllingRemote).toBe(false)
    })

    it('isControllingRemote is true when target device is set', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'd1', name: 'TV' }
      expect(store.isControllingRemote).toBe(true)
    })

    it('hasRemoteTarget is false when no target device', () => {
      const store = useRemoteControlStore()
      expect(store.hasRemoteTarget).toBe(false)
    })

    it('hasRemoteTarget is true when target device is set', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'd1' }
      expect(store.hasRemoteTarget).toBe(true)
    })
  })

  describe('setTargetDevice', () => {
    it('sets the targetDevice state', () => {
      const store = useRemoteControlStore()
      const device = { device_id: 'tv-01', name: 'Living Room TV' }
      store.setTargetDevice(device)
      expect(store.targetDevice).toEqual(device)
    })
  })

  describe('loadTargetSession', () => {
    it('loads the native session contract for streamarr devices', async () => {
      const store = useRemoteControlStore()
      store.setTargetDevice({ device_id: 'living-room', name: 'Living Room' })
      api.get.mockResolvedValueOnce({
        data: {
          device: { device_id: 'living-room', is_ws_connected: true },
          capabilities: { supports_play_queue: true },
          now_playing: { media_title: 'Alien', is_playing: true },
        },
      })

      const session = await store.loadTargetSession()

      expect(session.now_playing.media_title).toBe('Alien')
      expect(store.targetSession).toEqual(session)
      expect(store.targetDevice.is_ws_connected).toBe(true)
      expect(api.get).toHaveBeenCalledWith('/api/devices/by-id/living-room/session')
    })

    it('skips native session loading for cast targets', async () => {
      const store = useRemoteControlStore()
      const session = await store.loadTargetSession({ id: 'cast-1', protocol: 'chromecast' })

      expect(session).toBeNull()
      expect(api.get).not.toHaveBeenCalled()
    })
  })

  describe('target capabilities', () => {
    it('derives volume, queue, and message support from native session capabilities', async () => {
      const store = useRemoteControlStore()
      store.setTargetDevice({ device_id: 'living-room', name: 'Living Room' })
      api.get.mockResolvedValueOnce({
        data: {
          device: { device_id: 'living-room' },
          capabilities: {
            supported_commands: ['pause', 'message', 'next'],
            supports_display_message: true,
            supports_play_queue: true,
            supports_volume_control: true,
          },
        },
      })

      await store.loadTargetSession()

      expect(store.supportedCommands).toEqual(['pause', 'message', 'next'])
      expect(store.supportsDisplayMessage).toBe(true)
      expect(store.supportsQueueControl).toBe(true)
      expect(store.supportsVolumeControl).toBe(true)
      expect(store.isCommandSupported('message')).toBe(true)
      expect(store.isCommandSupported('seek')).toBe(false)
    })

    it('requires both display-message capability and message command support', async () => {
      const store = useRemoteControlStore()
      store.setTargetDevice({ device_id: 'living-room', name: 'Living Room' })
      api.get.mockResolvedValueOnce({
        data: {
          device: { device_id: 'living-room' },
          capabilities: {
            supported_commands: ['pause'],
            supports_display_message: true,
          },
        },
      })

      await store.loadTargetSession()

      expect(store.supportsDisplayMessage).toBe(false)
    })

    it('derives native cast capabilities from target protocol metadata', () => {
      const store = useRemoteControlStore()
      store.setTargetDevice({
        id: 'cast-living-room',
        protocol: 'chromecast',
        is_cast_target: true,
      })

      expect(store.supportedCommands).toContain('volume')
      expect(store.supportsVolumeControl).toBe(true)
      expect(store.supportsQueueControl).toBe(true)
    })
  })

  describe('clearTargetDevice', () => {
    it('clears the targetDevice state', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'tv-01' }
      store.clearTargetDevice()
      expect(store.targetDevice).toBeNull()
    })
  })

  describe('playbackOptionsForTarget', () => {
    it('uses registered streamarr device guid for backend capability lookup', () => {
      const store = useRemoteControlStore()
      expect(
        store.playbackOptionsForTarget({
          guid: 'device-guid',
          device_id: 'browser-1',
          protocol: 'streamarr',
        }),
      ).toEqual({ device_guid: 'device-guid' })
    })

    it('maps native cast protocols to playback profiles', () => {
      const store = useRemoteControlStore()
      expect(
        store.playbackOptionsForTarget({
          id: 'cast-living-room',
          protocol: 'chromecast',
        }),
      ).toEqual({ profile_id: 'chromecast' })
      expect(
        store.playbackOptionsForTarget({
          id: 'dlna-den',
          protocol: 'dlna',
        }),
      ).toEqual({ profile_id: 'dlna_generic' })
      expect(
        store.playbackOptionsForTarget({
          id: 'airplay-office',
          protocol: 'airplay',
        }),
      ).toEqual({ profile_id: 'browser' })
    })

    it('preserves explicit target playback profile', () => {
      const store = useRemoteControlStore()
      expect(
        store.playbackOptionsForTarget({
          id: 'custom-target',
          protocol: 'chromecast',
          playback_profile: 'living-room-custom',
        }),
      ).toEqual({ profile_id: 'living-room-custom' })
    })
  })

  describe('sendRemoteCommand', () => {
    it('returns false when no target device is set', async () => {
      const store = useRemoteControlStore()
      const result = await store.sendRemoteCommand('play')
      expect(result).toBe(false)
      expect(mockWs.send).not.toHaveBeenCalled()
    })

    it('posts streamarr device commands through the native device session API', async () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'd1' }

      const result = await store.sendRemoteCommand('pause')

      expect(result).toBe(true)
      expect(mockWs.send).not.toHaveBeenCalled()
      expect(api.post).toHaveBeenCalledWith('/api/devices/by-id/d1/commands', {
        command: 'pause',
        payload: {},
        from_device_id: 'controller-device',
      })
    })

    it('keeps a websocket-only sender for receiver-side command delivery', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'tv-42' }
      mockWs.isConnected.value = true

      store.sendRemoteCommandOverWebSocket('pause', { note: 'test' })

      expect(mockWs.send).toHaveBeenCalledWith({
        action: 'remote_control',
        target_device_id: 'tv-42',
        command: 'pause',
        payload: { note: 'test' },
      })
    })

    it('returns false from the websocket sender when WebSocket is not connected', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'd1' }
      mockWs.isConnected.value = false

      const result = store.sendRemoteCommandOverWebSocket('play')
      expect(result).toBe(false)
      expect(mockWs.send).not.toHaveBeenCalled()
    })

    it('returns the result from ws.send in websocket mode', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'x' }
      mockWs.isConnected.value = true
      mockWs.send.mockReturnValue(true)

      expect(store.sendRemoteCommandOverWebSocket('seek')).toBe(true)
    })

    it('uses empty payload by default in websocket mode', () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'x' }
      mockWs.isConnected.value = true

      store.sendRemoteCommandOverWebSocket('stop')

      expect(mockWs.send.mock.calls[0][0].payload).toEqual({})
    })

    it('posts commands to native cast targets instead of using websocket', async () => {
      const store = useRemoteControlStore()
      store.targetDevice = {
        id: 'chromecast-living-room',
        name: 'Living Room Chromecast',
        protocol: 'chromecast',
      }

      const result = await store.sendRemoteCommand('volume', { level: 0.5 })

      expect(result).toBe(true)
      expect(mockWs.send).not.toHaveBeenCalled()
      expect(api.post).toHaveBeenCalledWith('/api/cast/targets/chromecast-living-room/commands', {
        command: 'volume',
        payload: { level: 0.5 },
      })
    })

    it('returns false when native cast target command fails', async () => {
      api.post.mockRejectedValueOnce(new Error('offline'))
      const store = useRemoteControlStore()
      store.targetDevice = {
        id: 'airplay-den',
        name: 'Den AirPlay',
        protocol: 'airplay',
      }

      const result = await store.sendRemoteCommand('pause')

      expect(result).toBe(false)
    })
  })

  describe('sendPlayMediaCommand', () => {
    it('posts play media through the native device session endpoint', async () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'x' }

      await store.sendPlayMediaCommand('movies', 'movie-guid', 'Batman', 'file-guid')

      expect(api.post).toHaveBeenCalledWith('/api/devices/by-id/x/play-media', {
        media_type: 'movies',
        media_guid: 'movie-guid',
        media_title: 'Batman',
        file_guid: 'file-guid',
        from_device_id: 'controller-device',
      })
    })
  })

  describe('sendPauseCommand', () => {
    it('sends pause command with empty payload', async () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'x' }

      await store.sendPauseCommand()

      expect(api.post).toHaveBeenCalledWith('/api/devices/by-id/x/commands', {
        command: 'pause',
        payload: {},
        from_device_id: 'controller-device',
      })
    })
  })

  describe('sendSeekCommand', () => {
    it('sends seek command with position payload', async () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'x' }

      await store.sendSeekCommand(300)

      expect(api.post).toHaveBeenCalledWith('/api/devices/by-id/x/commands', {
        command: 'seek',
        payload: { position: 300 },
        from_device_id: 'controller-device',
      })
    })
  })

  describe('sendMessageCommand', () => {
    it('posts display messages through the native device message endpoint', async () => {
      const store = useRemoteControlStore()
      store.targetDevice = { device_id: 'living-room' }

      const result = await store.sendMessageCommand({
        title: 'Heads up',
        text: 'Dinner is ready',
        timeoutSeconds: 12,
      })

      expect(result).toBe(true)
      expect(api.post).toHaveBeenCalledWith('/api/devices/by-id/living-room/message', {
        title: 'Heads up',
        text: 'Dinner is ready',
        timeout_seconds: 12,
        from_device_id: 'controller-device',
      })
    })
  })

  describe('boot handler (remote_control)', () => {
    function registerBootHandler() {
      const router = { push: vi.fn() }
      bootRemoteControl({ router })
      const call = mockWs.on.mock.calls.find(([event]) => event === 'remote_control')
      return { router, handler: call?.[1] }
    }

    it('registers remote_control handler on the WebSocket', () => {
      const { handler } = registerBootHandler()
      expect(handler).toBeTypeOf('function')
    })

    it('ignores commands from a different user', () => {
      mockAuthStore.user = { guid: 'user-abc' }
      const store = useRemoteControlStore()
      const { router, handler } = registerBootHandler()

      handler({
        command: 'play',
        payload: { media_guid: 'movie-guid', media_type: 'movies' },
        from_device_id: 'other-device',
        from_user_id: 'user-xyz', // different user
      })

      expect(store.isRemoteControlled).toBe(false)
      expect(store.remoteController).toBeNull()
      expect(router.push).not.toHaveBeenCalled()
    })

    it('accepts play commands from the same user and navigates to the player', () => {
      mockAuthStore.user = { guid: 'user-abc' }
      const store = useRemoteControlStore()
      const { router, handler } = registerBootHandler()

      handler({
        command: 'play',
        payload: { media_guid: 'movie-guid', media_type: 'movies' },
        from_device_id: 'phone-01',
        from_user_id: 'user-abc',
      })

      expect(store.isRemoteControlled).toBe(true)
      expect(store.remoteController).toBe('phone-01')
      expect(router.push).toHaveBeenCalledWith({
        path: '/play/movie-guid',
        query: { type: 'movies' },
      })
    })

    it('ignores commands when user is not logged in (no auth user)', () => {
      mockAuthStore.user = null
      const store = useRemoteControlStore()
      const { router, handler } = registerBootHandler()

      handler({
        command: 'play',
        payload: { media_guid: 'movie-guid' },
        from_device_id: 'phone-01',
        from_user_id: 'user-xyz',
      })

      expect(store.isRemoteControlled).toBe(false)
      expect(router.push).not.toHaveBeenCalled()
    })
  })

  describe('clearRemoteControlled', () => {
    it('resets isRemoteControlled and remoteController', () => {
      const store = useRemoteControlStore()
      store.isRemoteControlled = true
      store.remoteController = 'phone-01'

      store.clearRemoteControlled()

      expect(store.isRemoteControlled).toBe(false)
      expect(store.remoteController).toBeNull()
    })
  })

})
