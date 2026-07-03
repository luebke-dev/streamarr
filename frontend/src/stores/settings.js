import { defineStore } from 'pinia'
import { LocalStorage } from 'quasar'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    language: LocalStorage.getItem('user-language') || 'en-US',
    availableLanguages: [
      { value: 'en-US', label: 'English', flag: '🇺🇸' },
      { value: 'de-DE', label: 'Deutsch', flag: '🇩🇪' },
    ],
    // System settings
    siteName: 'pyrate.media',
    siteNameLoaded: false,
    // Library settings
    libraries: {
      movies: true,
      shows: true,
      music: true,
      books: true,
      games: true,
    },
    librariesLoaded: false,
    // Available library plugins
    availableLibraries: [],
    availableLibrariesLoaded: false,
    // Subscription settings
    subscriptionsEnabled: false,
    subscriptionsLoaded: false,
    // Invite settings
    invitesEnabled: true,
    invitesLoaded: false,
    // Friends settings
    friendsEnabled: true,
    friendsLoaded: false,
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
      try {
        const response = await api.get('/api/settings/system')
        this.siteName = response.data.site_name || 'pyrate.media'
        this.siteNameLoaded = true
      } catch (error) {
        logger.error('Failed to fetch site name:', error)
        // Keep default value
      }
    },

    async updateSiteName(name) {
      try {
        const response = await api.put('/api/settings/system', {
          site_name: name,
        })
        this.siteName = response.data.site_name || 'pyrate.media'
        return true
      } catch (error) {
        logger.error('Failed to update site name:', error)
        throw error
      }
    },

    async fetchLibrariesSettings() {
      try {
        const response = await api.get('/api/settings/libraries')
        this.libraries = {
          movies: response.data.movies_enabled,
          shows: response.data.shows_enabled,
          music: response.data.music_enabled,
          books: response.data.books_enabled,
          games: response.data.games_enabled,
        }
        this.librariesLoaded = true
      } catch (error) {
        logger.error('Failed to fetch libraries settings:', error)
        // Keep default values (all enabled)
      }
    },

    async fetchAvailableLibraries() {
      try {
        // Fetch configured libraries (not plugins)
        const response = await api.get('/api/libraries')
        // API returns array directly, not {items: [...]}
        this.availableLibraries = response.data || []
        this.availableLibrariesLoaded = true
        logger.debug('[SettingsStore] Configured libraries loaded:', this.availableLibraries)
      } catch (error) {
        logger.error('Failed to fetch configured libraries:', error)
        this.availableLibraries = []
      }
    },

    async updateLibrariesSettings(settings) {
      try {
        const response = await api.put('/api/settings/libraries', {
          movies_enabled: settings.movies,
          shows_enabled: settings.shows,
          music_enabled: settings.music,
          books_enabled: settings.books,
          games_enabled: settings.games,
        })
        this.libraries = {
          movies: response.data.movies_enabled,
          shows: response.data.shows_enabled,
          music: response.data.music_enabled,
          books: response.data.books_enabled,
          games: response.data.games_enabled,
        }
        return true
      } catch (error) {
        logger.error('Failed to update libraries settings:', error)
        throw error
      }
    },

    async fetchSubscriptionSettings() {
      try {
        const response = await api.get('/api/settings/subscriptions')
        this.subscriptionsEnabled = response.data.subscriptions_enabled
        this.subscriptionsLoaded = true
      } catch (error) {
        logger.error('Failed to fetch subscription settings:', error)
        // Keep default value (disabled)
      }
    },

    async updateSubscriptionSettings(enabled) {
      try {
        const response = await api.put('/api/settings/subscriptions', {
          subscriptions_enabled: enabled,
        })
        this.subscriptionsEnabled = response.data.subscriptions_enabled
        return true
      } catch (error) {
        logger.error('Failed to update subscription settings:', error)
        throw error
      }
    },

    async fetchInviteSettings() {
      try {
        const response = await api.get('/api/settings/invites')
        this.invitesEnabled = response.data.invites_enabled
        this.invitesLoaded = true
      } catch (error) {
        logger.error('Failed to fetch invite settings:', error)
        // Keep default value (enabled)
      }
    },

    async updateInviteSettings(enabled) {
      try {
        const response = await api.put('/api/settings/invites', {
          invites_enabled: enabled,
        })
        this.invitesEnabled = response.data.invites_enabled
        return true
      } catch (error) {
        logger.error('Failed to update invite settings:', error)
        throw error
      }
    },

    async fetchFriendsSettings() {
      try {
        const response = await api.get('/api/settings/friends')
        this.friendsEnabled = response.data.friends_enabled
        this.friendsLoaded = true
      } catch (error) {
        logger.error('Failed to fetch friends settings:', error)
      }
    },

    async updateFriendsSettings(enabled) {
      try {
        const response = await api.put('/api/settings/friends', {
          friends_enabled: enabled,
        })
        this.friendsEnabled = response.data.friends_enabled
        return true
      } catch (error) {
        logger.error('Failed to update friends settings:', error)
        throw error
      }
    },
  },
})
