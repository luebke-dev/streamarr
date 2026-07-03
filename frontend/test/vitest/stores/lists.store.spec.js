import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('src/boot/axios', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}))

import { api } from 'src/boot/axios'
import {
  isAddableSearchResult,
  listItemTypeFromSearchResult,
  mediaGuidFromSearchResult,
  useListsStore,
} from 'src/stores/lists.js'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

// ─── Initial state ────────────────────────────────────────────────────────────

describe('initial state', () => {
  it('starts with empty lists and not initialized', () => {
    const store = useListsStore()
    expect(store.userLists).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.initialized).toBe(false)
  })
})

// ─── getListById ──────────────────────────────────────────────────────────────

describe('getListById', () => {
  it('returns undefined for a non-existent GUID', () => {
    const store = useListsStore()
    expect(store.getListById('not-here')).toBeUndefined()
  })

  it('finds a list by GUID', () => {
    const store = useListsStore()
    store.userLists = [
      { guid: 'abc-123', name: 'Watchlist' },
      { guid: 'def-456', name: 'Favorites' },
    ]
    expect(store.getListById('def-456')).toEqual({ guid: 'def-456', name: 'Favorites' })
  })

  it('returns undefined after clearLists', () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'abc', name: 'Test' }]
    store.clearLists()
    expect(store.getListById('abc')).toBeUndefined()
  })
})

// ─── clearLists ───────────────────────────────────────────────────────────────

describe('clearLists', () => {
  it('empties userLists and resets initialized flag', () => {
    const store = useListsStore()
    store.userLists = [
      { guid: '1', name: 'List A' },
      { guid: '2', name: 'List B' },
    ]
    store.initialized = true
    store.clearLists()
    expect(store.userLists).toEqual([])
    expect(store.initialized).toBe(false)
  })
})

// ─── createList ───────────────────────────────────────────────────────────────

describe('createList', () => {
  it('prepends the new list to userLists', async () => {
    const store = useListsStore()
    api.post.mockResolvedValueOnce({ data: { guid: 'new-guid', name: 'Test List' } })

    await store.createList({ name: 'Test List', description: '' })

    expect(store.userLists).toHaveLength(1)
    expect(store.userLists[0].guid).toBe('new-guid')
  })

  it('trims whitespace from the list name before sending to API', async () => {
    const store = useListsStore()
    api.post.mockResolvedValueOnce({ data: { guid: 'g1', name: 'My List' } })

    await store.createList({ name: '  My List  ' })

    expect(api.post).toHaveBeenCalledWith(
      '/api/lists',
      expect.objectContaining({ name: 'My List' }),
    )
  })

  it('sets item_count to 0 on the new local entry', async () => {
    const store = useListsStore()
    api.post.mockResolvedValueOnce({ data: { guid: 'g2' } })

    await store.createList({ name: 'Empty' })

    expect(store.userLists[0].item_count).toBe(0)
  })

  it('throws on API failure', async () => {
    const store = useListsStore()
    api.post.mockRejectedValueOnce(new Error('Server error'))

    await expect(store.createList({ name: 'Fail' })).rejects.toThrow('Server error')
  })
})

// ─── updateList ───────────────────────────────────────────────────────────────

describe('updateList', () => {
  it('updates the matching list in userLists', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'abc', name: 'Old Name', item_count: 3 }]
    api.put.mockResolvedValueOnce({ data: { guid: 'abc', name: 'New Name' } })

    await store.updateList('abc', { name: 'New Name' })

    expect(store.userLists[0].name).toBe('New Name')
  })

  it('does not modify other lists', async () => {
    const store = useListsStore()
    store.userLists = [
      { guid: 'abc', name: 'Target' },
      { guid: 'xyz', name: 'Other' },
    ]
    api.put.mockResolvedValueOnce({ data: { guid: 'abc', name: 'Updated' } })

    await store.updateList('abc', { name: 'Updated' })

    expect(store.userLists[1].name).toBe('Other')
  })
})

// ─── deleteList ───────────────────────────────────────────────────────────────

describe('deleteList', () => {
  it('removes the deleted list from userLists', async () => {
    const store = useListsStore()
    store.userLists = [
      { guid: 'del-me', name: 'Delete' },
      { guid: 'keep-me', name: 'Keep' },
    ]
    api.delete.mockResolvedValueOnce({})

    await store.deleteList('del-me')

    expect(store.userLists).toHaveLength(1)
    expect(store.userLists[0].guid).toBe('keep-me')
  })

  it('calls the correct endpoint', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1' }]
    api.delete.mockResolvedValueOnce({})

    await store.deleteList('list-1')

    expect(api.delete).toHaveBeenCalledWith('/api/lists/list-1')
  })
})

// ─── searchAddableItems ──────────────────────────────────────────────────────

describe('searchAddableItems', () => {
  const mediaGuid = '123e4567-e89b-12d3-a456-426614174000'

  it('skips the API call for blank queries', async () => {
    const store = useListsStore()

    const results = await store.searchAddableItems('   ')

    expect(results).toEqual([])
    expect(api.post).not.toHaveBeenCalled()
  })

  it('returns only in-library media items with a MediaItem GUID and supported type', async () => {
    const store = useListsStore()
    const localMovie = { id: mediaGuid, type: 'movie', in_library: true, title: 'Local Movie' }
    const providerMovie = { id: 550, tmdb_id: 550, type: 'movie', in_library: false }
    const brokenLibraryHit = { id: '550', type: 'movie', in_library: true }
    const unsupportedType = { id: mediaGuid, type: 'podcast', in_library: true }
    api.post.mockResolvedValueOnce({
      data: {
        hits: [localMovie, providerMovie, brokenLibraryHit, unsupportedType],
      },
    })

    const results = await store.searchAddableItems(' alien ')

    expect(api.post).toHaveBeenCalledWith('/api/search/', {
      query: 'alien',
      search_type: 'all',
      page: 1,
      per_page: 20,
    })
    expect(results).toEqual([localMovie])
  })

  it('exposes reusable addable-result helpers', () => {
    const hit = { id: mediaGuid, media_type: 'shows', in_library: true }

    expect(mediaGuidFromSearchResult(hit)).toBe(mediaGuid)
    expect(listItemTypeFromSearchResult(hit)).toBe('SHOW')
    expect(isAddableSearchResult(hit)).toBe(true)
    expect(isAddableSearchResult({ ...hit, id: 42 })).toBe(false)
    expect(isAddableSearchResult({ ...hit, in_library: false })).toBe(false)
  })
})

// ─── addItemToList ────────────────────────────────────────────────────────────

describe('addItemToList', () => {
  it('increments item_count in userLists', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', name: 'Test', item_count: 5 }]
    api.post.mockResolvedValueOnce({ data: { guid: 'new-item' } })

    await store.addItemToList('list-1', { media_guid: 'media-123' })

    expect(store.userLists[0].item_count).toBe(6)
  })

  it('prepends the item to currentListItems when viewing that list', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', item_count: 0 }]
    store.currentList = { guid: 'list-1', item_count: 0 }
    store.currentListItems = []
    api.post.mockResolvedValueOnce({ data: { guid: 'item-new' } })

    await store.addItemToList('list-1', { media_guid: 'm1' })

    expect(store.currentListItems).toHaveLength(1)
    expect(store.currentListItems[0].guid).toBe('item-new')
    expect(store.currentList.item_count).toBe(1)
  })

  it('does not touch currentListItems when viewing a different list', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', item_count: 2 }]
    store.currentList = { guid: 'other-list', item_count: 10 }
    store.currentListItems = [{ guid: 'existing-item' }]
    api.post.mockResolvedValueOnce({ data: { guid: 'added-item' } })

    await store.addItemToList('list-1', { media_guid: 'm1' })

    expect(store.currentListItems).toHaveLength(1)
    expect(store.currentList.item_count).toBe(10)
  })
})

// ─── removeItemFromList ───────────────────────────────────────────────────────

describe('removeItemFromList', () => {
  it('decrements item_count in userLists', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', item_count: 3 }]
    api.delete.mockResolvedValueOnce({})

    await store.removeItemFromList('list-1', 'item-to-remove')

    expect(store.userLists[0].item_count).toBe(2)
  })

  it('never decrements item_count below zero', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', item_count: 0 }]
    api.delete.mockResolvedValueOnce({})

    await store.removeItemFromList('list-1', 'phantom-item')

    expect(store.userLists[0].item_count).toBe(0)
  })

  it('removes the item from currentListItems when viewing that list', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', item_count: 2 }]
    store.currentList = { guid: 'list-1', item_count: 2 }
    store.currentListItems = [{ guid: 'item-A' }, { guid: 'item-B' }]
    api.delete.mockResolvedValueOnce({})

    await store.removeItemFromList('list-1', 'item-A')

    expect(store.currentListItems).toHaveLength(1)
    expect(store.currentListItems[0].guid).toBe('item-B')
    expect(store.currentList.item_count).toBe(1)
  })

  it('does not touch currentListItems when viewing a different list', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'list-1', item_count: 5 }]
    store.currentList = { guid: 'other-list', item_count: 5 }
    store.currentListItems = [{ guid: 'item-X' }]
    api.delete.mockResolvedValueOnce({})

    await store.removeItemFromList('list-1', 'item-X')

    expect(store.currentListItems).toHaveLength(1)
  })
})

// ─── fetchUserLists ───────────────────────────────────────────────────────────

describe('fetchUserLists', () => {
  it('clears userLists and skips API call when no userGuid is provided', async () => {
    const store = useListsStore()
    store.userLists = [{ guid: 'stale' }]

    await store.fetchUserLists(null)

    expect(api.get).not.toHaveBeenCalled()
    expect(store.userLists).toEqual([])
  })

  it('populates userLists from the API response', async () => {
    api.get.mockResolvedValueOnce({ data: { items: [{ guid: 'l1', name: 'My List' }] } })
    const store = useListsStore()

    await store.fetchUserLists('user-guid-123')

    expect(store.userLists).toHaveLength(1)
    expect(store.userLists[0].guid).toBe('l1')
    expect(store.initialized).toBe(true)
  })

  it('resets userLists to empty on API failure', async () => {
    api.get.mockRejectedValueOnce(new Error('Server error'))
    const store = useListsStore()
    store.userLists = [{ guid: 'stale' }]

    await store.fetchUserLists('user-guid')

    expect(store.userLists).toEqual([])
  })
})
