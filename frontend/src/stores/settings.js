import { defineStore } from 'pinia'
import { LocalStorage } from 'quasar'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'

// Shared libraries <-> API field mapping, used by both fetch and update so the
// two directions can never drift apart.
function librariesFromResponse(data) {
  return {
    movies: data.movies_enabled,
    shows: data.shows_enabled,
    music: data.music_enabled,
    books: data.books_enabled,
    games: data.games_enabled,
  }
}

function librariesToPayload(settings) {
  return {
    movies_enabled: settings.movies,
    shows_enabled: settings.shows,
    music_enabled: settings.music,
    books_enabled: settings.books,
    games_enabled: settings.games,
  }
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    language: LocalStorage.getItem('user-language') || 'en-US',
    availableLanguages: [
      { value: 'en-US', label: 'English', flag: '🇺🇸' },
      { value: 'de-DE', label: 'Deutsch', flag: '🇩🇪' },
    ],
    // System settings
    siteName: 'Streamarr',
    siteNameLoaded: false,
    siteNameError: null,
    // Library settings
    libraries: {
      movies: true,
      shows: true,
      music: true,
      books: true,
      games: true,
    },
    librariesLoaded: false,
    librariesError: null,
    // Available library plugins
    availableLibraries: [],
    availableLibrariesLoaded: false,
    availableLibrariesError: null,
    // Subscription settings
    subscriptionsEnabled: false,
    subscriptionsLoaded: false,
    subscriptionsError: null,
    // Invite settings
    invitesEnabled: true,
    invitesLoaded: false,
    invitesError: null,
    // Friends settings
    friendsEnabled: true,
    friendsLoaded: false,
    friendsError: null,
  }),

  getters: {
    currentLanguage: (state) => {
      return (
        state.availableLanguages.find((lang) => lang.value === state.language) ||
        state.availableLanguages[0]
      )
    },
    getSiteName: (state) => state.siteName,
    isMoviesEnabled: (state) => state.libraries.movies,
    isShowsEnabled: (state) => state.libraries.shows,
    isMusicEnabled: (state) => state.libraries.music,
    isBooksEnabled: (state) => state.libraries.books,
    isGamesEnabled: (state) => state.libraries.games,
    isSubscriptionsEnabled: (state) => state.subscriptionsEnabled,
    isInvitesEnabled: (state) => state.invitesEnabled,
    isFriendsEnabled: (state) => state.friendsEnabled,
  },

  actions: {
    // Generic fetch/update for the boolean setting groups that follow the
    // `${prefix}Enabled` / `${prefix}Loaded` / `${prefix}Error` convention.
    async _fetchFlag(prefix, endpoint, field) {
      this[`${prefix}Error`] = null
      try {
        const response = await api.get(endpoint)
        this[`${prefix}Enabled`] = response.data[field]
        this[`${prefix}Loaded`] = true
      } catch (error) {
        this[`${prefix}Error`] = error
        logger.error(`Failed to fetch ${prefix} settings:`, error)
        // Keep default value
      }
    },

    async _updateFlag(prefix, endpoint, field, enabled) {
      try {
        const response = await api.put(endpoint, { [field]: enabled })
        this[`${prefix}Enabled`] = response.data[field]
        return true
      } catch (error) {
        logger.error(`Failed to update ${prefix} settings:`, error)
        throw error
      }
    },

    setLanguage(locale) {
      this.language = locale
      LocalStorage.set('user-language', locale)
    },

    initializeLanguage() {
      const savedLanguage = LocalStorage.getItem('user-language')
      if (savedLanguage && this.availableLanguages.some((lang) => lang.value === savedLanguage)) {
        this.language = savedLanguage
      } else {
        // Try to detect browser language
        const browserLanguage = navigator.language || navigator.languages[0]
        const supportedLanguage = this.availableLanguages.find((lang) =>
          browserLanguage.startsWith(lang.value.split('-')[0]),
        )

        if (supportedLanguage) {
          this.language = supportedLanguage.value
          LocalStorage.set('user-language', supportedLanguage.value)
        } else {
          this.language = 'en-US' // fallback
          LocalStorage.set('user-language', 'en-US')
        }
      }
    },

    async fetchSiteName() {
      this.siteNameError = null
      try {
        const response = await api.get('/api/settings/system')
        this.siteName = response.data.site_name || 'Streamarr'
        this.siteNameLoaded = true
      } catch (error) {
        this.siteNameError = error
        logger.error('Failed to fetch site name:', error)
        // Keep default value
      }
    },

    async updateSiteName(name) {
      try {
        const response = await api.put('/api/settings/system', {
          site_name: name,
        })
        this.siteName = response.data.site_name || 'Streamarr'
        return true
      } catch (error) {
        logger.error('Failed to update site name:', error)
        throw error
      }
    },

    async fetchLibrariesSettings() {
      this.librariesError = null
      try {
        const response = await api.get('/api/settings/libraries')
        this.libraries = librariesFromResponse(response.data)
        this.librariesLoaded = true
      } catch (error) {
        this.librariesError = error
        logger.error('Failed to fetch libraries settings:', error)
        // Keep default values (all enabled)
      }
    },

    async fetchAvailableLibraries() {
      this.availableLibrariesError = null
      try {
        // Fetch configured libraries (not plugins)
        const response = await api.get('/api/libraries')
        // API returns array directly, not {items: [...]}
        this.availableLibraries = response.data || []
        this.availableLibrariesLoaded = true
        logger.debug('[SettingsStore] Configured libraries loaded:', this.availableLibraries)
      } catch (error) {
        this.availableLibrariesError = error
        logger.error('Failed to fetch configured libraries:', error)
        this.availableLibraries = []
      }
    },

    async updateLibrariesSettings(settings) {
      try {
        const response = await api.put('/api/settings/libraries', librariesToPayload(settings))
        this.libraries = librariesFromResponse(response.data)
        return true
      } catch (error) {
        logger.error('Failed to update libraries settings:', error)
        throw error
      }
    },

    async fetchSubscriptionSettings() {
      return this._fetchFlag('subscriptions', '/api/settings/subscriptions', 'subscriptions_enabled')
    },

    async updateSubscriptionSettings(enabled) {
      return this._updateFlag(
        'subscriptions',
        '/api/settings/subscriptions',
        'subscriptions_enabled',
        enabled,
      )
    },

    async fetchInviteSettings() {
      return this._fetchFlag('invites', '/api/settings/invites', 'invites_enabled')
    },

    async updateInviteSettings(enabled) {
      return this._updateFlag('invites', '/api/settings/invites', 'invites_enabled', enabled)
    },

    async fetchFriendsSettings() {
      return this._fetchFlag('friends', '/api/settings/friends', 'friends_enabled')
    },

    async updateFriendsSettings(enabled) {
      return this._updateFlag('friends', '/api/settings/friends', 'friends_enabled', enabled)
    },
  },
})
