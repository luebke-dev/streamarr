import { defineStore } from 'pinia'
import { api } from 'src/boot/axios'
import { ref, computed } from 'vue'
import { useAuthStore } from './auth'
import { logger } from 'src/utils/logger'

export const searchTypeToListItemType = {
  movie: 'MOVIE',
  movies: 'MOVIE',
  show: 'SHOW',
  shows: 'SHOW',
  series: 'SHOW',
  episode: 'EPISODE',
  game: 'GAME',
  games: 'GAME',
  music: 'MUSIC',
  artist: 'MUSIC',
  album: 'MUSIC',
  song: 'MUSIC',
  book: 'BOOK',
  books: 'BOOK',
  audiobook: 'AUDIOBOOK',
}

const MEDIA_GUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function mediaGuidFromSearchResult(item) {
  const guid = item?.id || item?.guid || item?.media_guid || null
  return typeof guid === 'string' && MEDIA_GUID_PATTERN.test(guid) ? guid : null
}

export function listItemTypeFromSearchResult(item) {
  const rawType = String(item?.type || item?.media_type || '').toLowerCase()
  return searchTypeToListItemType[rawType] || null
}

export function isAddableSearchResult(item) {
  return (
    item?.in_library === true &&
    Boolean(mediaGuidFromSearchResult(item) && listItemTypeFromSearchResult(item))
  )
}

export const useListsStore = defineStore('lists', () => {
  // Use refs for reactivity
  const userLists = ref([])
  const currentList = ref(null)
  const currentListItems = ref([])
  const loading = ref(false)
  const loadingList = ref(false)
  const loadingItems = ref(false)
  const initialized = ref(false)

  let userListsRequestId = 0
  let currentListRequestId = 0
  let listItemsRequestId = 0

  // Getters as computed properties
  const getUserLists = computed(() => userLists.value)
  const isLoading = computed(() => loading.value)
  const isLoadingList = computed(() => loadingList.value)
  const isLoadingItems = computed(() => loadingItems.value)
  const getCurrentList = computed(() => currentList.value)
  const getCurrentListItems = computed(() => currentListItems.value)
  const getListById = computed(() => (listId) => {
    return userLists.value.find((list) => list.guid === listId)
  })

  // Actions as functions
  async function fetchUserLists(userGuid) {
    const currentRequest = ++userListsRequestId

    if (!userGuid) {
      userLists.value = []
      return
    }

    try {
      loading.value = true

      const response = await api.get(`/api/lists`, {
        params: {
          per_page: 50,
          owner_guid: userGuid,
        },
      })

      if (currentRequest !== userListsRequestId) return
      userLists.value = response.data.items || []
      initialized.value = true
    } catch (error) {
      if (currentRequest !== userListsRequestId) return
      logger.error('[ListsStore] Failed to fetch user lists:', error)
      userLists.value = []
    } finally {
      if (currentRequest === userListsRequestId) {
        loading.value = false
      }
    }
  }

  async function createList(listData) {
    try {
      const response = await api.post('/api/lists', {
        description: listData.description || '',
        list_type: 'user',
        visibility: 'private',
        ...listData,
        name: listData.name.trim(), // always trim, must come after spread
      })

      // Add the new list to the store immediately
      const newList = {
        guid: response.data.guid,
        name: listData.name.trim(),
        item_count: 0,
        created_at: new Date().toISOString(),
        ...response.data,
      }

      userLists.value.unshift(newList)

      return response.data
    } catch (error) {
      logger.error('[ListsStore] Failed to create list:', error)
      throw error
    }
  }

  async function updateList(listId, listData) {
    try {
      const response = await api.put(`/api/lists/${listId}`, listData)

      // Update the list in the store
      const index = userLists.value.findIndex((list) => list.guid === listId)
      if (index !== -1) {
        userLists.value[index] = { ...userLists.value[index], ...response.data }
      }

      return response.data
    } catch (error) {
      logger.error('Failed to update list:', error)
      throw error
    }
  }

  async function deleteList(listId) {
    try {
      await api.delete(`/api/lists/${listId}`)

      // Remove the list from the store
      const index = userLists.value.findIndex((list) => list.guid === listId)
      if (index !== -1) {
        userLists.value.splice(index, 1)
      }
    } catch (error) {
      logger.error('Failed to delete list:', error)
      throw error
    }
  }

  function clearLists() {
    userLists.value = []
    initialized.value = false
  }

  // Fetch individual list details
  async function fetchList(listId) {
    if (!listId) {
      return null
    }

    const currentRequest = ++currentListRequestId

    try {
      loadingList.value = true

      const response = await api.get(`/api/lists/${listId}`)

      if (currentRequest === currentListRequestId) {
        currentList.value = response.data
      }

      return response.data
    } catch (error) {
      logger.error('[ListsStore] Failed to fetch list details:', error)
      if (currentRequest === currentListRequestId) {
        currentList.value = null
      }
      throw error
    } finally {
      if (currentRequest === currentListRequestId) {
        loadingList.value = false
      }
    }
  }

  // Fetch individual playlist details through the playlist wrapper API
  async function fetchPlaylist(playlistId) {
    if (!playlistId) {
      return null
    }

    const currentRequest = ++currentListRequestId

    try {
      loadingList.value = true

      const response = await api.get(`/api/playlists/${playlistId}`)

      if (currentRequest === currentListRequestId) {
        currentList.value = response.data
      }

      return response.data
    } catch (error) {
      logger.error('[ListsStore] Failed to fetch playlist details:', error)
      if (currentRequest === currentListRequestId) {
        currentList.value = null
      }
      throw error
    } finally {
      if (currentRequest === currentListRequestId) {
        loadingList.value = false
      }
    }
  }

  // Fetch list items
  async function fetchListItems(listId, page = 1, perPage = 24) {
    if (!listId) {
      return { items: [], total: 0, totalPages: 1 }
    }

    const currentRequest = ++listItemsRequestId

    try {
      loadingItems.value = true

      const response = await api.get(`/api/lists/${listId}/items`, {
        params: {
          page,
          per_page: perPage,
        },
      })

      if (currentRequest === listItemsRequestId) {
        currentListItems.value = response.data.items || []
      }

      return {
        items: response.data.items || [],
        total: response.data.total || 0,
        totalPages: response.data.total_pages || 1,
      }
    } catch (error) {
      logger.error('[ListsStore] Failed to fetch list items:', error)
      if (currentRequest === listItemsRequestId) {
        currentListItems.value = []
      }
      throw error
    } finally {
      if (currentRequest === listItemsRequestId) {
        loadingItems.value = false
      }
    }
  }

  // Fetch playlist items through the playlist wrapper API
  async function fetchPlaylistItems(playlistId, page = 1, perPage = 24) {
    if (!playlistId) {
      return { items: [], total: 0, totalPages: 1 }
    }

    const currentRequest = ++listItemsRequestId

    try {
      loadingItems.value = true

      const response = await api.get(`/api/playlists/${playlistId}/items`, {
        params: {
          page,
          per_page: perPage,
        },
      })

      if (currentRequest === listItemsRequestId) {
        currentListItems.value = response.data.items || []
      }

      return {
        items: response.data.items || [],
        total: response.data.total || 0,
        totalPages: response.data.total_pages || 1,
      }
    } catch (error) {
      logger.error('[ListsStore] Failed to fetch playlist items:', error)
      if (currentRequest === listItemsRequestId) {
        currentListItems.value = []
      }
      throw error
    } finally {
      if (currentRequest === listItemsRequestId) {
        loadingItems.value = false
      }
    }
  }

  async function fetchPlaylistQueue(playlistId, options = {}) {
    if (!playlistId) {
      return null
    }

    try {
      const response = await api.get(`/api/playlists/${playlistId}/queue`, {
        params: {
          start_index: options.startIndex ?? 0,
          start_item_guid: options.startItemGuid || undefined,
        },
      })
      return response.data
    } catch (error) {
      logger.error('[ListsStore] Failed to fetch playlist queue:', error)
      throw error
    }
  }

  async function searchAddableItems(query, options = {}) {
    const trimmedQuery = String(query || '').trim()
    if (!trimmedQuery) {
      return []
    }

    try {
      const response = await api.post('/api/search/', {
        query: trimmedQuery,
        search_type: options.searchType || 'all',
        page: options.page ?? 1,
        per_page: options.perPage ?? 20,
      })
      return (response.data?.hits || []).filter(isAddableSearchResult)
    } catch (error) {
      logger.error('[ListsStore] Failed to search addable list items:', error)
      throw error
    }
  }

  // Add item to list
  async function addItemToList(listId, itemData) {
    try {
      const response = await api.post(`/api/lists/${listId}/items`, itemData)

      // Always update the user lists item count first
      const userList = userLists.value.find((list) => list.guid === listId)
      if (userList) {
        userList.item_count += 1
      }

      // Update current list items if we're viewing this list
      if (currentList.value && currentList.value.guid === listId) {
        currentListItems.value.unshift(response.data)
        currentList.value.item_count += 1
      }

      return response.data
    } catch (error) {
      logger.error('[ListsStore] Failed to add item to list:', error)
      throw error
    }
  }

  // Remove item from list
  async function removeItemFromList(listId, itemId) {
    try {
      await api.delete(`/api/lists/${listId}/items/${itemId}`)

      // Always update the user lists item count first
      const userList = userLists.value.find((list) => list.guid === listId)
      if (userList) {
        userList.item_count = Math.max(0, userList.item_count - 1)
      }

      // Update current list items if we're viewing this list
      if (currentList.value && currentList.value.guid === listId) {
        const index = currentListItems.value.findIndex((item) => item.guid === itemId)
        if (index !== -1) {
          currentListItems.value.splice(index, 1)
          currentList.value.item_count = Math.max(0, currentList.value.item_count - 1)
        }
      }
    } catch (error) {
      logger.error('[ListsStore] Failed to remove item from list:', error)
      throw error
    }
  }

  // Like/unlike list
  async function toggleListLike(listId) {
    const authStore = useAuthStore()
    const userGuid = authStore.user?.guid
    const list = currentList.value?.guid === listId ? currentList.value : null
    const existingLike = (list?.user_interactions || []).find(
      (interaction) =>
        interaction.interaction_type === 'like' &&
        (!userGuid || interaction.user_guid === userGuid),
    )

    try {
      if (existingLike) {
        await api.delete(`/api/lists/${listId}/interactions/like`)

        // Update current list if we're viewing it
        if (list) {
          list.like_count = Math.max(0, (list.like_count || 0) - 1)
          list.user_interactions = (list.user_interactions || []).filter(
            (interaction) => interaction !== existingLike,
          )
        }
      } else {
        await api.post(`/api/lists/${listId}/interactions`, {
          interaction_type: 'like',
        })

        // Update current list if we're viewing it
        if (list) {
          list.like_count = (list.like_count || 0) + 1
          if (userGuid) {
            list.user_interactions = [
              ...(list.user_interactions || []),
              { interaction_type: 'like', user_guid: userGuid, list_guid: listId },
            ]
          }
        }
      }
    } catch (error) {
      logger.error('[ListsStore] Failed to like list:', error)
      throw error
    }
  }

  // Clear current list data
  function clearCurrentList() {
    currentList.value = null
    currentListItems.value = []
  }

  // Update list item count when items are added/removed
  function updateListItemCount(listId, newCount) {
    const list = userLists.value.find((list) => list.guid === listId)
    if (list) {
      list.item_count = newCount
    }
  }

  return {
    // State
    userLists,
    currentList,
    currentListItems,
    loading,
    loadingList,
    loadingItems,
    initialized,
    // Getters
    getUserLists,
    isLoading,
    isLoadingList,
    isLoadingItems,
    getCurrentList,
    getCurrentListItems,
    getListById,
    // Actions
    fetchUserLists,
    fetchList,
    fetchPlaylist,
    fetchListItems,
    fetchPlaylistItems,
    fetchPlaylistQueue,
    searchAddableItems,
    createList,
    updateList,
    deleteList,
    addItemToList,
    removeItemFromList,
    toggleListLike,
    clearLists,
    clearCurrentList,
    updateListItemCount,
  }
})
