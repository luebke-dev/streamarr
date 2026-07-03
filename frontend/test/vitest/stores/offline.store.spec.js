import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('src/boot/axios', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const mockAuthStore = vi.hoisted(() => ({
  deviceId: 'web-device',
}))

vi.mock('stores/auth', () => ({
  useAuthStore: () => mockAuthStore,
}))

import { api } from 'src/boot/axios'
import { useOfflineStore } from 'src/stores/offline'

describe('useOfflineStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockAuthStore.deviceId = 'web-device'
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:offline-media')
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('loads the current device by stable device id', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        items: [
          { guid: 'other-guid', device_id: 'other-device' },
          { guid: 'device-guid', device_id: 'web-device' },
        ],
      },
    })

    const store = useOfflineStore()
    const device = await store.loadCurrentDevice()

    expect(device.guid).toBe('device-guid')
    expect(api.get).toHaveBeenCalledWith('/api/devices/me', { params: { page_size: 100 } })
  })

  it('fetches a manifest for the current device', async () => {
    api.get
      .mockResolvedValueOnce({ data: { items: [{ guid: 'device-guid', device_id: 'web-device' }] } })
      .mockResolvedValueOnce({ data: { items: [{ media_guid: 'media-1' }], total: 1 } })

    const store = useOfflineStore()
    const manifest = await store.fetchManifest()

    expect(manifest.total).toBe(1)
    expect(api.get).toHaveBeenLastCalledWith('/api/devices/device-guid/offline-items/manifest')
  })

  it('creates an authenticated blob URL for a ready manifest item', async () => {
    const blob = new Blob(['media'])
    api.get
      .mockResolvedValueOnce({ data: { items: [{ guid: 'device-guid', device_id: 'web-device' }] } })
      .mockResolvedValueOnce({
        data: {
          items: [
            {
              media_guid: 'media-1',
              file_guid: 'file-1',
              status: 'ready',
              download_url: '/api/media/media-1/files/file-1/download',
            },
          ],
          total: 1,
        },
      })
      .mockResolvedValueOnce({ data: blob })

    const store = useOfflineStore()
    const entry = await store.createObjectUrlForMedia('media-1')

    expect(entry.url).toBe('blob:offline-media')
    expect(entry.item.file_guid).toBe('file-1')
    expect(api.get).toHaveBeenLastCalledWith('/api/media/media-1/files/file-1/download', {
      responseType: 'blob',
    })
  })

  it('does not create an object URL for non-ready items', async () => {
    api.get
      .mockResolvedValueOnce({ data: { items: [{ guid: 'device-guid', device_id: 'web-device' }] } })
      .mockResolvedValueOnce({
        data: {
          items: [
            {
              media_guid: 'media-1',
              status: 'queued',
              download_url: '/api/media/media-1/files/file-1/download',
            },
          ],
          total: 1,
        },
      })

    const store = useOfflineStore()
    const entry = await store.createObjectUrlForMedia('media-1')

    expect(entry).toBeNull()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('does not create an object URL for expired manifest items', async () => {
    api.get
      .mockResolvedValueOnce({ data: { items: [{ guid: 'device-guid', device_id: 'web-device' }] } })
      .mockResolvedValueOnce({
        data: {
          items: [
            {
              media_guid: 'media-1',
              status: 'ready',
              expires_at: '2000-01-01T00:00:00Z',
              download_url: '/api/media/media-1/files/file-1/download',
            },
          ],
          total: 1,
        },
      })

    const store = useOfflineStore()
    const entry = await store.createObjectUrlForMedia('media-1')

    expect(entry).toBeNull()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('loads per-device offline items and counts status values', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        items: [
          { media_guid: 'media-1', status: 'queued' },
          { media_guid: 'media-2', status: 'removed' },
        ],
        total: 2,
      },
    })

    const store = useOfflineStore()
    const response = await store.fetchDeviceOfflineItems('device-guid')

    expect(response.total).toBe(2)
    expect(store.offlineStatusCounts(response.items)).toMatchObject({
      queued: 1,
      removed: 1,
      ready: 0,
    })
  })

  it('preserves backend rejection details for offline sync requests', async () => {
    api.get.mockResolvedValueOnce({
      data: { items: [{ guid: 'device-guid', device_id: 'web-device' }] },
    })
    api.post.mockRejectedValueOnce({
      response: { data: { detail: 'Offline download limit exceeded' } },
    })

    const store = useOfflineStore()
    await expect(store.requestOfflineSync('media-1')).rejects.toBeTruthy()

    expect(store.requestErrorMessage).toBe('Offline download limit exceeded')
  })

  it('revokes cached object URLs', async () => {
    const blob = new Blob(['media'])
    api.get
      .mockResolvedValueOnce({ data: { items: [{ guid: 'device-guid', device_id: 'web-device' }] } })
      .mockResolvedValueOnce({
        data: {
          items: [
            {
              media_guid: 'media-1',
              status: 'ready',
              download_url: '/api/media/media-1/files/file-1/download',
            },
          ],
          total: 1,
        },
      })
      .mockResolvedValueOnce({ data: blob })

    const store = useOfflineStore()
    await store.createObjectUrlForMedia('media-1')

    store.releaseObjectUrl('media-1')

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:offline-media')
    expect(store.objectUrls).toEqual({})
  })
})
