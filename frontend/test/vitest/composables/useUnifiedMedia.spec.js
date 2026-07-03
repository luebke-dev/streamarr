import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

import { api } from 'boot/axios'
import { invalidateApiCache } from 'src/composables/useApiResponseCache'
import {
  listMediaItems,
  getMediaItem,
  createMediaItem,
  updateMediaItem,
  deleteMediaItem,
  searchMediaItems,
  getMediaItemChildren,
  getShowHierarchy,
  getAlbumTracks,
  getMediaItemReleases,
  createMediaRelease,
  getMediaItemByExternalId,
  updateMediaAvailability,
  MediaTypes,
  AvailabilityStatus,
} from 'src/composables/useUnifiedMedia'

describe('useUnifiedMedia', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    invalidateApiCache(() => true)
    api.get.mockResolvedValue({ data: {} })
    api.post.mockResolvedValue({ data: {} })
    api.patch.mockResolvedValue({ data: {} })
    api.delete.mockResolvedValue({ data: null })
  })

  describe('MediaTypes constants', () => {
    it('has correct string values', () => {
      expect(MediaTypes.MOVIES).toBe('MOVIES')
      expect(MediaTypes.SHOWS).toBe('SHOWS')
      expect(MediaTypes.GAMES).toBe('GAMES')
      expect(MediaTypes.MUSIC).toBe('MUSIC')
      expect(MediaTypes.BOOKS).toBe('BOOKS')
    })

    it('SERIES is an alias for SHOWS', () => {
      expect(MediaTypes.SERIES).toBe('SHOWS')
      expect(MediaTypes.SERIES).toBe(MediaTypes.SHOWS)
    })
  })

  describe('AvailabilityStatus constants', () => {
    it('has all expected status values', () => {
      expect(AvailabilityStatus.UNKNOWN).toBe('unknown')
      expect(AvailabilityStatus.AVAILABLE).toBe('available')
      expect(AvailabilityStatus.DOWNLOADABLE).toBe('downloadable')
      expect(AvailabilityStatus.UNAVAILABLE).toBe('unavailable')
    })
  })

  describe('listMediaItems', () => {
    it('calls GET /api/media and returns response data', async () => {
      const mockData = { items: [{ guid: '1', title: 'Movie A' }], total: 1 }
      api.get.mockResolvedValue({ data: mockData })

      const result = await listMediaItems({ media_type: 'MOVIES', page: 2 })

      expect(api.get).toHaveBeenCalledWith('/api/media', {
        params: { media_type: 'MOVIES', page: 2 },
      })
      expect(result).toEqual(mockData)
    })

    it('passes empty params when called without arguments', async () => {
      await listMediaItems()
      expect(api.get).toHaveBeenCalledWith('/api/media', { params: {} })
    })
  })

  describe('getMediaItem', () => {
    it('calls GET /api/media/:guid and returns data', async () => {
      const mockData = { guid: 'abc-123', title: 'Test Movie' }
      api.get.mockResolvedValue({ data: mockData })

      const result = await getMediaItem('abc-123')

      expect(api.get).toHaveBeenCalledWith('/api/media/abc-123', {
        params: { load_files: true, load_releases: true, load_external_ids: true },
      })
      expect(result).toEqual(mockData)
    })

    it('enables all load flags by default', async () => {
      await getMediaItem('guid-1')
      expect(api.get.mock.calls[0][1].params).toEqual({
        load_files: true,
        load_releases: true,
        load_external_ids: true,
      })
    })

    it('respects load_files: false', async () => {
      await getMediaItem('guid-1', { load_files: false })
      expect(api.get.mock.calls[0][1].params.load_files).toBe(false)
      expect(api.get.mock.calls[0][1].params.load_releases).toBe(true)
    })

    it('respects load_releases: false', async () => {
      await getMediaItem('guid-1', { load_releases: false })
      expect(api.get.mock.calls[0][1].params.load_releases).toBe(false)
      expect(api.get.mock.calls[0][1].params.load_files).toBe(true)
    })

    it('respects load_external_ids: false', async () => {
      await getMediaItem('guid-1', { load_external_ids: false })
      expect(api.get.mock.calls[0][1].params.load_external_ids).toBe(false)
    })
  })

  describe('createMediaItem', () => {
    it('calls POST /api/media and returns created item', async () => {
      const newItem = { title: 'New Movie', media_type: 'MOVIES' }
      const created = { guid: 'new-guid', ...newItem }
      api.post.mockResolvedValue({ data: created })

      const result = await createMediaItem(newItem)

      expect(api.post).toHaveBeenCalledWith('/api/media', newItem)
      expect(result).toEqual(created)
    })
  })

  describe('updateMediaItem', () => {
    it('calls PATCH /api/media/:guid and returns updated item', async () => {
      const updateData = { title: 'Updated Title' }
      const updated = { guid: 'abc', title: 'Updated Title' }
      api.patch.mockResolvedValue({ data: updated })

      const result = await updateMediaItem('abc', updateData)

      expect(api.patch).toHaveBeenCalledWith('/api/media/abc', updateData)
      expect(result).toEqual(updated)
    })
  })

  describe('deleteMediaItem', () => {
    it('calls DELETE /api/media/:guid', async () => {
      await deleteMediaItem('abc-123')
      expect(api.delete).toHaveBeenCalledWith('/api/media/abc-123')
    })

    it('returns the response data', async () => {
      api.delete.mockResolvedValue({ data: { detail: 'Deleted' } })
      const result = await deleteMediaItem('abc-123')
      expect(result).toEqual({ detail: 'Deleted' })
    })
  })

  describe('searchMediaItems', () => {
    it('calls GET /api/media/search/query with q param', async () => {
      const mockResults = { items: [{ guid: '1', title: 'Batman' }], total: 1 }
      api.get.mockResolvedValue({ data: mockResults })

      const result = await searchMediaItems('batman')

      expect(api.get).toHaveBeenCalledWith('/api/media/search/query', {
        params: { q: 'batman' },
      })
      expect(result).toEqual(mockResults)
    })

    it('merges additional options into params', async () => {
      await searchMediaItems('batman', { media_type: 'MOVIES', limit: 10 })
      expect(api.get).toHaveBeenCalledWith('/api/media/search/query', {
        params: { q: 'batman', media_type: 'MOVIES', limit: 10 },
      })
    })
  })

  describe('getMediaItemChildren', () => {
    it('orders by sequence by default', async () => {
      await getMediaItemChildren('show-guid')
      expect(api.get).toHaveBeenCalledWith('/api/media/show-guid/children', {
        params: { order_by_sequence: true },
      })
    })

    it('can disable ordering by sequence', async () => {
      await getMediaItemChildren('show-guid', false)
      expect(api.get).toHaveBeenCalledWith('/api/media/show-guid/children', {
        params: { order_by_sequence: false },
      })
    })

    it('returns response data', async () => {
      const mockData = { items: [{ guid: 's01', title: 'Season 1' }] }
      api.get.mockResolvedValue({ data: mockData })
      const result = await getMediaItemChildren('show-guid')
      expect(result).toEqual(mockData)
    })
  })

  describe('getShowHierarchy', () => {
    it('calls the show hierarchy endpoint', async () => {
      await getShowHierarchy('show-guid')
      expect(api.get).toHaveBeenCalledWith('/api/media/shows/show-guid/hierarchy')
    })

    it('returns response data', async () => {
      const mockHierarchy = { seasons: [{ season_number: 1, episodes: [] }] }
      api.get.mockResolvedValue({ data: mockHierarchy })
      const result = await getShowHierarchy('show-guid')
      expect(result).toEqual(mockHierarchy)
    })
  })

  describe('getAlbumTracks', () => {
    it('calls the album tracks endpoint', async () => {
      await getAlbumTracks('album-guid')
      expect(api.get).toHaveBeenCalledWith('/api/media/albums/album-guid/tracks')
    })
  })

  describe('getMediaItemReleases', () => {
    it('calls releases endpoint with pagination params', async () => {
      await getMediaItemReleases('item-guid', { page: 2, per_page: 10 })
      expect(api.get).toHaveBeenCalledWith('/api/media/item-guid/releases', {
        params: { page: 2, per_page: 10 },
      })
    })

    it('uses empty params object by default', async () => {
      await getMediaItemReleases('item-guid')
      expect(api.get).toHaveBeenCalledWith('/api/media/item-guid/releases', { params: {} })
    })
  })

  describe('createMediaRelease', () => {
    it('calls POST releases endpoint with release data', async () => {
      const releaseData = { name: 'BluRay 1080p', quality: '1080p' }
      const created = { guid: 'rel-guid', ...releaseData }
      api.post.mockResolvedValue({ data: created })

      const result = await createMediaRelease('item-guid', releaseData)

      expect(api.post).toHaveBeenCalledWith('/api/media/item-guid/releases', releaseData)
      expect(result).toEqual(created)
    })
  })

  describe('getMediaItemByExternalId', () => {
    it('calls external ID endpoint with media type filter', async () => {
      await getMediaItemByExternalId('tmdb', '12345', 'MOVIES')
      expect(api.get).toHaveBeenCalledWith('/api/media/external/tmdb/12345', {
        params: { media_type: 'MOVIES' },
      })
    })

    it('passes empty params when no media type given', async () => {
      await getMediaItemByExternalId('igdb', '67890')
      expect(api.get).toHaveBeenCalledWith('/api/media/external/igdb/67890', { params: {} })
    })

    it('uses the correct provider and external ID in URL', async () => {
      await getMediaItemByExternalId('anidb', 'a-9999')
      expect(api.get.mock.calls[0][0]).toBe('/api/media/external/anidb/a-9999')
    })
  })

  describe('updateMediaAvailability', () => {
    it('calls PATCH availability endpoint with status param', async () => {
      await updateMediaAvailability('item-guid', 'available')
      expect(api.patch).toHaveBeenCalledWith('/api/media/item-guid/availability', null, {
        params: { status: 'available' },
      })
    })

    it('works with AvailabilityStatus constants', async () => {
      await updateMediaAvailability('item-guid', AvailabilityStatus.UNAVAILABLE)
      expect(api.patch.mock.calls[0][2].params.status).toBe('unavailable')
    })
  })
})
