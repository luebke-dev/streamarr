import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('src/boot/axios', () => ({
  api: {
    defaults: { headers: { common: {} } },
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { api } from 'src/boot/axios'
import { useListsStore } from 'src/stores/lists.js'
import { useAuthStore } from 'src/stores/auth.js'

/** Create a promise with externally controllable resolve/reject. */
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.clearAllMocks()
})

// ─── fetchList: stale responses must not win ─────────────────────────────────

describe('fetchList request-id guard', () => {
  it('ignores a slow old response that arrives after a newer one', async () => {
    const store = useListsStore()
    const slowOld = deferred()

    api.get.mockImplementationOnce(() => slowOld.promise)
    const oldRun = store.fetchList('old-list')

    api.get.mockResolvedValueOnce({ data: { guid: 'new-list', name: 'New' } })
    const newRun = store.fetchList('new-list')

    await newRun
    expect(store.currentList.guid).toBe('new-list')
    expect(store.loadingList).toBe(false)

    // Old response arrives late — must not overwrite the newer list.
    slowOld.resolve({ data: { guid: 'old-list', name: 'Old' } })
    await oldRun

    expect(store.currentList.guid).toBe('new-list')
    expect(store.loadingList).toBe(false)
  })

  it('does not clear the newer list when a superseded fetch fails late', async () => {
    const store = useListsStore()
    const slowOld = deferred()

    api.get.mockImplementationOnce(() => slowOld.promise)
    const oldRun = store.fetchList('old-list')

    api.get.mockResolvedValueOnce({ data: { guid: 'new-list' } })
    await store.fetchList('new-list')

    slowOld.reject(new Error('timeout'))
    await expect(oldRun).rejects.toThrow('timeout')

    expect(store.currentList.guid).toBe('new-list')
    expect(store.loadingList).toBe(false)
  })
})

// ─── fetchListItems: stale responses must not win ────────────────────────────

describe('fetchListItems request-id guard', () => {
  it('ignores slow old items that arrive after newer ones', async () => {
    const store = useListsStore()
    const slowOld = deferred()

    api.get.mockImplementationOnce(() => slowOld.promise)
    const oldRun = store.fetchListItems('old-list')

    api.get.mockResolvedValueOnce({
      data: { items: [{ guid: 'new-item' }], total: 1, total_pages: 1 },
    })
    const newRun = store.fetchListItems('new-list')

    await newRun
    expect(store.currentListItems).toEqual([{ guid: 'new-item' }])
    expect(store.loadingItems).toBe(false)

    slowOld.resolve({ data: { items: [{ guid: 'stale-item' }], total: 1, total_pages: 1 } })
    await oldRun

    expect(store.currentListItems).toEqual([{ guid: 'new-item' }])
    expect(store.loadingItems).toBe(false)
  })

  it('does not clear newer items when a superseded fetch fails late', async () => {
    const store = useListsStore()
    const slowOld = deferred()

    api.get.mockImplementationOnce(() => slowOld.promise)
    const oldRun = store.fetchListItems('old-list')

    api.get.mockResolvedValueOnce({
      data: { items: [{ guid: 'new-item' }], total: 1, total_pages: 1 },
    })
    await store.fetchListItems('new-list')

    slowOld.reject(new Error('timeout'))
    await expect(oldRun).rejects.toThrow('timeout')

    expect(store.currentListItems).toEqual([{ guid: 'new-item' }])
    expect(store.loadingItems).toBe(false)
  })
})

// ─── toggleListLike: real toggle in both directions ──────────────────────────

describe('toggleListLike', () => {
  it('likes via POST and increments like_count when there is no existing like', async () => {
    const store = useListsStore()
    const authStore = useAuthStore()
    authStore.user = { guid: 'user-1' }
    store.currentList = { guid: 'list-1', like_count: 0, user_interactions: [] }
    api.post.mockResolvedValueOnce({ data: {} })

    await store.toggleListLike('list-1')

    expect(api.post).toHaveBeenCalledWith('/api/lists/list-1/interactions', {
      interaction_type: 'like',
    })
    expect(api.delete).not.toHaveBeenCalled()
    expect(store.currentList.like_count).toBe(1)
    expect(store.currentList.user_interactions).toEqual([
      { interaction_type: 'like', user_guid: 'user-1', list_guid: 'list-1' },
    ])
  })

  it('unlikes via DELETE /interactions/like and decrements like_count when a like exists', async () => {
    const store = useListsStore()
    const authStore = useAuthStore()
    authStore.user = { guid: 'user-1' }
    store.currentList = {
      guid: 'list-1',
      like_count: 3,
      user_interactions: [{ interaction_type: 'like', user_guid: 'user-1', list_guid: 'list-1' }],
    }
    api.delete.mockResolvedValueOnce({ data: {} })

    await store.toggleListLike('list-1')

    expect(api.delete).toHaveBeenCalledWith('/api/lists/list-1/interactions/like')
    expect(api.post).not.toHaveBeenCalled()
    expect(store.currentList.like_count).toBe(2)
    expect(store.currentList.user_interactions).toEqual([])
  })

  it('round-trips like then unlike back to the initial state', async () => {
    const store = useListsStore()
    const authStore = useAuthStore()
    authStore.user = { guid: 'user-1' }
    store.currentList = { guid: 'list-1', like_count: 0, user_interactions: [] }
    api.post.mockResolvedValueOnce({ data: {} })
    api.delete.mockResolvedValueOnce({ data: {} })

    await store.toggleListLike('list-1')
    expect(store.currentList.like_count).toBe(1)

    await store.toggleListLike('list-1')
    expect(store.currentList.like_count).toBe(0)
    expect(store.currentList.user_interactions).toEqual([])
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.delete).toHaveBeenCalledTimes(1)
  })

  it("does not treat another user's like as the current user's like", async () => {
    const store = useListsStore()
    const authStore = useAuthStore()
    authStore.user = { guid: 'user-1' }
    store.currentList = {
      guid: 'list-1',
      like_count: 1,
      user_interactions: [{ interaction_type: 'like', user_guid: 'someone-else' }],
    }
    api.post.mockResolvedValueOnce({ data: {} })

    await store.toggleListLike('list-1')

    expect(api.post).toHaveBeenCalledWith('/api/lists/list-1/interactions', {
      interaction_type: 'like',
    })
    expect(store.currentList.like_count).toBe(2)
  })

  it('never decrements like_count below zero on unlike', async () => {
    const store = useListsStore()
    const authStore = useAuthStore()
    authStore.user = { guid: 'user-1' }
    store.currentList = {
      guid: 'list-1',
      like_count: 0,
      user_interactions: [{ interaction_type: 'like', user_guid: 'user-1' }],
    }
    api.delete.mockResolvedValueOnce({ data: {} })

    await store.toggleListLike('list-1')

    expect(store.currentList.like_count).toBe(0)
  })
})
