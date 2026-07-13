import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const { mockLocalStorageGetItem, mockLocalStorageSet } = vi.hoisted(() => ({
  mockLocalStorageGetItem: vi.fn().mockReturnValue(null),
  mockLocalStorageSet: vi.fn(),
}))

vi.mock('quasar', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    LocalStorage: {
      getItem: mockLocalStorageGetItem,
      set: mockLocalStorageSet,
    },
  }
})

const mockApi = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('boot/axios', () => ({ api: mockApi }))

import { useSettingsStore } from 'src/stores/settings'

describe('useSettingsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockLocalStorageGetItem.mockReturnValue(null)
    mockApi.get.mockResolvedValue({ data: {} })
    mockApi.put.mockResolvedValue({ data: {} })
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('initial state', () => {
    it('defaults language to en-US when no saved language', () => {
      const store = useSettingsStore()
      expect(store.language).toBe('en-US')
    })

    it('initialises language from LocalStorage when a valid language is saved', () => {
      mockLocalStorageGetItem.mockReturnValue('de-DE')
      const store = useSettingsStore()
      expect(store.language).toBe('de-DE')
    })

    it('has all libraries enabled by default', () => {
      const store = useSettingsStore()
      expect(store.libraries).toEqual({
        movies: true,
        shows: true,
        music: true,
        books: true,
        games: true,
      })
    })

    it('has default site name', () => {
      const store = useSettingsStore()
      expect(store.siteName).toBe('streamarr.media')
      expect(store.siteNameLoaded).toBe(false)
    })

    it('has subscriptions disabled by default', () => {
      const store = useSettingsStore()
      expect(store.subscriptionsEnabled).toBe(false)
    })

    it('has invites enabled by default', () => {
      const store = useSettingsStore()
      expect(store.invitesEnabled).toBe(true)
    })
  })

  describe('currentLanguage getter', () => {
    it('returns the matching language object for en-US', () => {
      const store = useSettingsStore()
      store.language = 'en-US'
      expect(store.currentLanguage).toEqual({ value: 'en-US', label: 'English', flag: '🇺🇸' })
    })

    it('returns the matching language object for de-DE', () => {
      const store = useSettingsStore()
      store.language = 'de-DE'
      expect(store.currentLanguage).toEqual({ value: 'de-DE', label: 'Deutsch', flag: '🇩🇪' })
    })

    it('falls back to the first available language for unknown locale', () => {
      const store = useSettingsStore()
      store.language = 'fr-FR'
      expect(store.currentLanguage).toEqual(store.availableLanguages[0])
    })
  })

  describe('getSiteName getter', () => {
    it('returns the current site name', () => {
      const store = useSettingsStore()
      store.siteName = 'My Server'
      expect(store.getSiteName).toBe('My Server')
    })
  })

  describe('library getters', () => {
    it('isMoviesEnabled reflects libraries.movies', () => {
      const store = useSettingsStore()
      expect(store.isMoviesEnabled).toBe(true)
      store.libraries.movies = false
      expect(store.isMoviesEnabled).toBe(false)
    })

    it('isShowsEnabled reflects libraries.shows', () => {
      const store = useSettingsStore()
      store.libraries.shows = false
      expect(store.isShowsEnabled).toBe(false)
    })

    it('isMusicEnabled reflects libraries.music', () => {
      const store = useSettingsStore()
      store.libraries.music = false
      expect(store.isMusicEnabled).toBe(false)
    })

    it('isBooksEnabled reflects libraries.books', () => {
      const store = useSettingsStore()
      store.libraries.books = false
      expect(store.isBooksEnabled).toBe(false)
    })

    it('isGamesEnabled reflects libraries.games', () => {
      const store = useSettingsStore()
      store.libraries.games = false
      expect(store.isGamesEnabled).toBe(false)
    })

    it('isSubscriptionsEnabled defaults to false', () => {
      const store = useSettingsStore()
      expect(store.isSubscriptionsEnabled).toBe(false)
    })

    it('isInvitesEnabled defaults to true', () => {
      const store = useSettingsStore()
      expect(store.isInvitesEnabled).toBe(true)
    })
  })

  describe('setLanguage', () => {
    it('updates state.language', () => {
      const store = useSettingsStore()
      store.setLanguage('de-DE')
      expect(store.language).toBe('de-DE')
    })

    it('persists the new locale to LocalStorage', () => {
      const store = useSettingsStore()
      store.setLanguage('de-DE')
      expect(mockLocalStorageSet).toHaveBeenCalledWith('user-language', 'de-DE')
    })
  })

  describe('initializeLanguage', () => {
    it('uses saved language when it is a valid option', () => {
      mockLocalStorageGetItem.mockReturnValue('de-DE')
      const store = useSettingsStore()
      store.initializeLanguage()
      expect(store.language).toBe('de-DE')
    })

    it('ignores invalid saved language and falls through to browser detection', () => {
      mockLocalStorageGetItem.mockReturnValue('fr-FR')
      const store = useSettingsStore()
      store.language = 'en-US'
      store.initializeLanguage()
      expect(store.language).not.toBe('fr-FR')
    })

    it('detects German browser language and sets de-DE', () => {
      mockLocalStorageGetItem.mockReturnValue(null)
      vi.stubGlobal('navigator', { language: 'de', languages: ['de'] })
      const store = useSettingsStore()
      store.initializeLanguage()
      expect(store.language).toBe('de-DE')
    })

    it('falls back to en-US when browser language is unsupported', () => {
      mockLocalStorageGetItem.mockReturnValue(null)
      vi.stubGlobal('navigator', { language: 'zh-CN', languages: ['zh-CN'] })
      const store = useSettingsStore()
      store.initializeLanguage()
      expect(store.language).toBe('en-US')
      expect(mockLocalStorageSet).toHaveBeenCalledWith('user-language', 'en-US')
    })
  })

  describe('fetchSiteName', () => {
    it('sets siteName and siteNameLoaded on success', async () => {
      mockApi.get.mockResolvedValue({ data: { site_name: 'My Media Server' } })
      const store = useSettingsStore()
      await store.fetchSiteName()
      expect(store.siteName).toBe('My Media Server')
      expect(store.siteNameLoaded).toBe(true)
    })

    it('uses default streamarr.media when site_name is null', async () => {
      mockApi.get.mockResolvedValue({ data: { site_name: null } })
      const store = useSettingsStore()
      await store.fetchSiteName()
      expect(store.siteName).toBe('streamarr.media')
    })

    it('does not change siteName or set loaded flag on error', async () => {
      mockApi.get.mockRejectedValue(new Error('Network error'))
      const store = useSettingsStore()
      await store.fetchSiteName()
      expect(store.siteName).toBe('streamarr.media')
      expect(store.siteNameLoaded).toBe(false)
    })

    it('calls GET /api/settings/system', async () => {
      const store = useSettingsStore()
      await store.fetchSiteName()
      expect(mockApi.get).toHaveBeenCalledWith('/api/settings/system')
    })
  })

  describe('updateSiteName', () => {
    it('calls PUT /api/settings/system and updates siteName', async () => {
      mockApi.put.mockResolvedValue({ data: { site_name: 'New Name' } })
      const store = useSettingsStore()
      const result = await store.updateSiteName('New Name')
      expect(mockApi.put).toHaveBeenCalledWith('/api/settings/system', { site_name: 'New Name' })
      expect(store.siteName).toBe('New Name')
      expect(result).toBe(true)
    })

    it('throws on API error', async () => {
      mockApi.put.mockRejectedValue(new Error('Server error'))
      const store = useSettingsStore()
      await expect(store.updateSiteName('Bad')).rejects.toThrow('Server error')
    })
  })

  describe('fetchLibrariesSettings', () => {
    it('updates libraries from API response', async () => {
      mockApi.get.mockResolvedValue({
        data: {
          movies_enabled: true,
          shows_enabled: false,
          music_enabled: true,
          books_enabled: false,
          games_enabled: true,
        },
      })
      const store = useSettingsStore()
      await store.fetchLibrariesSettings()
      expect(store.libraries).toEqual({
        movies: true,
        shows: false,
        music: true,
        books: false,
        games: true,
      })
      expect(store.librariesLoaded).toBe(true)
    })

    it('does not set librariesLoaded on error', async () => {
      mockApi.get.mockRejectedValue(new Error('Network error'))
      const store = useSettingsStore()
      await store.fetchLibrariesSettings()
      expect(store.librariesLoaded).toBe(false)
    })
  })

  describe('fetchSubscriptionSettings', () => {
    it('updates subscriptionsEnabled from API', async () => {
      mockApi.get.mockResolvedValue({ data: { subscriptions_enabled: true } })
      const store = useSettingsStore()
      await store.fetchSubscriptionSettings()
      expect(store.subscriptionsEnabled).toBe(true)
      expect(store.subscriptionsLoaded).toBe(true)
    })
  })

  describe('fetchInviteSettings', () => {
    it('updates invitesEnabled from API', async () => {
      mockApi.get.mockResolvedValue({ data: { invites_enabled: false } })
      const store = useSettingsStore()
      await store.fetchInviteSettings()
      expect(store.invitesEnabled).toBe(false)
      expect(store.invitesLoaded).toBe(true)
    })
  })
})
