import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import { api } from 'boot/axios'
import { useBannerStore } from 'src/stores/banners.js'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

// ─── Initial state ────────────────────────────────────────────────────────────

describe('initial state', () => {
  it('starts with no active banners', () => {
    const store = useBannerStore()
    expect(store.activeBanners).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })
})

// ─── hasBanners getter ────────────────────────────────────────────────────────

describe('hasBanners', () => {
  it('returns false when activeBanners is empty', () => {
    const store = useBannerStore()
    expect(store.hasBanners).toBe(false)
  })

  it('returns true when there is at least one banner', () => {
    const store = useBannerStore()
    store.activeBanners = [{ guid: 'b1', message: 'Hello' }]
    expect(store.hasBanners).toBe(true)
  })
})

// ─── visibleBanners getter ────────────────────────────────────────────────────

describe('visibleBanners', () => {
  it('returns the activeBanners array', () => {
    const store = useBannerStore()
    const banners = [{ guid: 'b1' }, { guid: 'b2' }]
    store.activeBanners = banners
    expect(store.visibleBanners).toEqual(banners)
  })
})

// ─── clearBanners ─────────────────────────────────────────────────────────────

describe('clearBanners', () => {
  it('resets banners, loading, and error to initial values', () => {
    const store = useBannerStore()
    store.activeBanners = [{ guid: 'b1' }]
    store.loading = true
    store.error = 'something broke'

    store.clearBanners()

    expect(store.activeBanners).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })
})

// ─── fetchActiveBanners ───────────────────────────────────────────────────────

describe('fetchActiveBanners', () => {
  it('populates activeBanners on a successful API call', async () => {
    const store = useBannerStore()
    api.get.mockResolvedValueOnce({ data: [{ guid: 'b1', message: 'Welcome' }] })

    await store.fetchActiveBanners()

    expect(store.activeBanners).toHaveLength(1)
    expect(store.activeBanners[0].guid).toBe('b1')
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('calls the correct endpoint', async () => {
    const store = useBannerStore()
    api.get.mockResolvedValueOnce({ data: [] })

    await store.fetchActiveBanners()

    expect(api.get).toHaveBeenCalledWith('/api/banners/active')
  })

  it('sets error and clears banners when the API call fails with a server error message', async () => {
    const store = useBannerStore()
    api.get.mockRejectedValueOnce({ response: { data: { detail: 'Forbidden' } } })

    await store.fetchActiveBanners()

    expect(store.activeBanners).toEqual([])
    expect(store.error).toBe('Forbidden')
    expect(store.loading).toBe(false)
  })

  it('sets a generic error message when there is no server response detail', async () => {
    const store = useBannerStore()
    api.get.mockRejectedValueOnce(new Error('Network error'))

    await store.fetchActiveBanners()

    expect(store.error).toBe('Failed to load banners')
    expect(store.loading).toBe(false)
  })
})

// ─── dismissBanner ────────────────────────────────────────────────────────────

describe('dismissBanner', () => {
  it('removes the dismissed banner from activeBanners', async () => {
    const store = useBannerStore()
    store.activeBanners = [
      { guid: 'keep-me', message: 'Stay' },
      { guid: 'dismiss-me', message: 'Bye' },
    ]
    api.post.mockResolvedValueOnce({})

    await store.dismissBanner('dismiss-me')

    expect(store.activeBanners).toHaveLength(1)
    expect(store.activeBanners[0].guid).toBe('keep-me')
  })

  it('calls the correct endpoint', async () => {
    const store = useBannerStore()
    store.activeBanners = [{ guid: 'b1' }]
    api.post.mockResolvedValueOnce({})

    await store.dismissBanner('b1')

    expect(api.post).toHaveBeenCalledWith('/api/banners/b1/dismiss')
  })

  it('leaves activeBanners unchanged if the banner GUID is not found', async () => {
    const store = useBannerStore()
    store.activeBanners = [{ guid: 'b1' }, { guid: 'b2' }]
    api.post.mockResolvedValueOnce({})

    await store.dismissBanner('nonexistent')

    expect(store.activeBanners).toHaveLength(2)
  })

  it('throws when the API call fails', async () => {
    const store = useBannerStore()
    store.activeBanners = [{ guid: 'b1' }]
    api.post.mockRejectedValueOnce(new Error('Server error'))

    await expect(store.dismissBanner('b1')).rejects.toThrow('Server error')
  })
})
