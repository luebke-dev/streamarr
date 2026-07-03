import { ref, reactive } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

// 404/403 from optional sub-resources (e.g. user without stats yet) is normal —
// log at debug. Anything else is unexpected and should be visible.
function logSectionError(name, err) {
  const status = err?.response?.status
  if (status === 404 || status === 403) {
    logger.debug(`${name} not available (${status})`)
  } else {
    logger.error(`Failed to load ${name}:`, err)
  }
}

/**
 * Composable für das Laden aller Detail-Daten eines Admin-User-Profils.
 * Kapselt die 8 unabhängigen Loader-Aufrufe (User, Stats, History, Downloads,
 * Invites, Friendships, Devices, Lists) inkl. eigener Loading-State Refs.
 *
 * @param {() => string} guidGetter  Funktion die die User-GUID liefert (reaktiv)
 * @param {(key: string) => string} t  i18n-Übersetzungsfunktion (für Fehlermeldungen)
 */
export function useUserDetails(guidGetter, t) {
  // -- User -----------------------------------------------------------
  const loading = ref(true)
  const error = ref(null)
  const user = ref(null)

  const loadUser = async () => {
    loading.value = true
    error.value = null
    try {
      const response = await api.get(`/api/users/${guidGetter()}`)
      user.value = response.data
    } catch (err) {
      logger.error('Failed to load user:', err)
      if (err.response?.status === 404) {
        error.value = t('adminUserPage.errorNotFound')
      } else if (err.response?.status === 403) {
        error.value = t('adminUserPage.errorForbidden')
      } else {
        error.value = t('adminUserPage.errorLoad')
      }
    } finally {
      loading.value = false
    }
  }

  // -- Stats ----------------------------------------------------------
  const stats = reactive({
    invites_created: 0,
    movies_watched: 0,
    episodes_watched: 0,
    lists_created: 0,
  })

  const loadUserStats = async () => {
    try {
      const response = await api.get(`/api/users/${guidGetter()}/stats`)
      const data = response.data
      stats.movies_watched = data.total_movies_watched || 0
      stats.episodes_watched = data.total_episodes_watched || 0
    } catch (err) {
      logSectionError('user stats', err)
    }
  }

  // -- Viewing History (paginiert) -----------------------------------
  const historyLoading = ref(false)
  const historyItems = ref([])
  const historyPagination = ref({
    page: 1,
    rowsPerPage: 10,
    rowsNumber: 0,
  })

  const loadViewingHistory = async (page = 1, perPage = 10) => {
    historyLoading.value = true
    try {
      const response = await api.get(`/api/users/${guidGetter()}/viewing-history`, {
        params: { page, per_page: perPage },
      })
      historyItems.value = response.data.items
      historyPagination.value.rowsNumber = response.data.total
      historyPagination.value.page = page
      historyPagination.value.rowsPerPage = perPage
    } catch (err) {
      logSectionError('viewing history', err)
    } finally {
      historyLoading.value = false
    }
  }

  const onHistoryRequest = (props) => {
    loadViewingHistory(props.pagination.page, props.pagination.rowsPerPage)
  }

  // -- Downloads ------------------------------------------------------
  const downloadsLoading = ref(false)
  const userDownloads = ref([])

  const loadUserDownloads = async () => {
    downloadsLoading.value = true
    try {
      const response = await api.get('/api/downloads', {
        params: { user_guid: guidGetter() },
      })
      userDownloads.value = response.data
    } catch (err) {
      logSectionError('user downloads', err)
    } finally {
      downloadsLoading.value = false
    }
  }

  // -- Invites --------------------------------------------------------
  const invitesLoading = ref(false)
  const userInvites = ref([])

  const loadUserInvites = async () => {
    invitesLoading.value = true
    try {
      const response = await api.get(`/api/users/${guidGetter()}/invites`)
      userInvites.value = response.data
      stats.invites_created = userInvites.value.length
    } catch (err) {
      logSectionError('user invites', err)
    } finally {
      invitesLoading.value = false
    }
  }

  // -- Friendships ----------------------------------------------------
  const friendshipsLoading = ref(false)
  const userFriendships = ref([])

  const loadUserFriendships = async () => {
    friendshipsLoading.value = true
    try {
      const response = await api.get(`/api/users/${guidGetter()}/friendships`)
      userFriendships.value = response.data
    } catch (err) {
      logSectionError('user friendships', err)
    } finally {
      friendshipsLoading.value = false
    }
  }

  // -- Devices --------------------------------------------------------
  const devicesLoading = ref(false)
  const userDevices = ref([])

  const loadUserDevices = async () => {
    devicesLoading.value = true
    try {
      const response = await api.get(`/api/devices/user/${guidGetter()}`)
      userDevices.value = response.data.items || response.data
    } catch (err) {
      logSectionError('user devices', err)
    } finally {
      devicesLoading.value = false
    }
  }

  // -- Lists ----------------------------------------------------------
  const listsLoading = ref(false)
  const userLists = ref([])

  const loadUserLists = async () => {
    listsLoading.value = true
    try {
      const response = await api.get(`/api/lists/users/${guidGetter()}/lists`)
      userLists.value = response.data.items || response.data
      stats.lists_created = userLists.value.length
    } catch (err) {
      logSectionError('user lists', err)
    } finally {
      listsLoading.value = false
    }
  }

  /** Lädt alle Detail-Sections parallel. */
  const loadAll = () => {
    loadUser()
    loadUserStats()
    loadViewingHistory()
    loadUserDownloads()
    loadUserInvites()
    loadUserFriendships()
    loadUserDevices()
    loadUserLists()
  }

  return {
    // User
    loading,
    error,
    user,
    loadUser,
    // Stats
    stats,
    loadUserStats,
    // History
    historyLoading,
    historyItems,
    historyPagination,
    loadViewingHistory,
    onHistoryRequest,
    // Downloads
    downloadsLoading,
    userDownloads,
    loadUserDownloads,
    // Invites
    invitesLoading,
    userInvites,
    loadUserInvites,
    // Friendships
    friendshipsLoading,
    userFriendships,
    loadUserFriendships,
    // Devices
    devicesLoading,
    userDevices,
    loadUserDevices,
    // Lists
    listsLoading,
    userLists,
    loadUserLists,
    // Bulk
    loadAll,
  }
}
