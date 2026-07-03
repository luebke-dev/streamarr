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
import { useAuthStore } from 'src/stores/auth.js'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  // Reset the Authorization header mock state
  api.defaults.headers.common = {}
  vi.clearAllMocks()
})

// ─── Initial state ────────────────────────────────────────────────────────────

describe('initial state', () => {
  it('starts unauthenticated with no user', () => {
    const store = useAuthStore()
    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
    expect(store.accessToken).toBeNull()
  })

  it('is not logged in initially', () => {
    const store = useAuthStore()
    expect(store.isLoggedIn).toBe(false)
  })
})

// ─── isLoggedIn computed ──────────────────────────────────────────────────────

describe('isLoggedIn', () => {
  it('is false when authenticated flag is true but user is null', () => {
    const store = useAuthStore()
    store.isAuthenticated = true
    store.user = null
    expect(store.isLoggedIn).toBe(false)
  })

  it('is false when user is set but isAuthenticated is false', () => {
    const store = useAuthStore()
    store.isAuthenticated = false
    store.user = { id: 1 }
    expect(store.isLoggedIn).toBe(false)
  })

  it('is true when both isAuthenticated and user are set', () => {
    const store = useAuthStore()
    store.isAuthenticated = true
    store.user = { id: 1 }
    expect(store.isLoggedIn).toBe(true)
  })
})

// ─── isSuperuser / isAdmin ────────────────────────────────────────────────────

describe('isSuperuser / isAdmin', () => {
  it('returns false when user is null', () => {
    const store = useAuthStore()
    expect(store.isSuperuser).toBe(false)
    expect(store.isAdmin).toBe(false)
  })

  it('returns false when is_superuser is false', () => {
    const store = useAuthStore()
    store.user = { is_superuser: false }
    expect(store.isSuperuser).toBe(false)
    expect(store.isAdmin).toBe(false)
  })

  it('returns true when user.is_superuser is true', () => {
    const store = useAuthStore()
    store.user = { is_superuser: true }
    expect(store.isSuperuser).toBe(true)
    expect(store.isAdmin).toBe(true)
  })
})

// ─── userDisplayName ─────────────────────────────────────────────────────────

describe('userDisplayName', () => {
  it('returns empty string when user is null', () => {
    const store = useAuthStore()
    expect(store.userDisplayName).toBe('')
  })

  it('returns the trimmed full name when first and last name are set', () => {
    const store = useAuthStore()
    store.user = {
      first_name: 'Alice',
      last_name: 'Smith',
      preferred_username: 'asmith',
      email: 'a@b.com',
    }
    expect(store.userDisplayName).toBe('Alice Smith')
  })

  it('falls back to preferred_username when full name is blank', () => {
    const store = useAuthStore()
    store.user = { first_name: '', last_name: '', preferred_username: 'asmith', email: 'a@b.com' }
    expect(store.userDisplayName).toBe('asmith')
  })

  it('falls back to email when both name and username are blank', () => {
    const store = useAuthStore()
    store.user = {
      first_name: '',
      last_name: '',
      preferred_username: '',
      email: 'user@example.com',
    }
    expect(store.userDisplayName).toBe('user@example.com')
  })
})

// ─── Language getters ─────────────────────────────────────────────────────────

describe('language getters', () => {
  it('returns defaults when no user is set', () => {
    const store = useAuthStore()
    expect(store.uiLanguage).toBe('en-US')
    expect(store.audioLanguages).toEqual(['en'])
    expect(store.subtitleLanguage).toBeNull()
  })

  it('returns user language preferences when a user is set', () => {
    const store = useAuthStore()
    store.user = { ui_language: 'de-DE', audio_languages: ['de'], subtitle_language: 'en' }
    expect(store.uiLanguage).toBe('de-DE')
    expect(store.audioLanguages).toEqual(['de'])
    expect(store.subtitleLanguage).toBe('en')
  })
})

// ─── Token management ─────────────────────────────────────────────────────────

describe('saveTokensToStorage', () => {
  it('persists tokens in localStorage', () => {
    const store = useAuthStore()
    store.saveTokensToStorage('access-abc', 'refresh-xyz')
    expect(localStorage.getItem('access_token')).toBe('access-abc')
    expect(localStorage.getItem('refresh_token')).toBe('refresh-xyz')
  })

  it('updates the store refs', () => {
    const store = useAuthStore()
    store.saveTokensToStorage('access-abc', 'refresh-xyz')
    expect(store.accessToken).toBe('access-abc')
    expect(store.refreshToken).toBe('refresh-xyz')
  })

  it('sets the Authorization header on the api instance', () => {
    const store = useAuthStore()
    store.saveTokensToStorage('access-abc', 'refresh-xyz')
    expect(api.defaults.headers.common['Authorization']).toBe('Bearer access-abc')
  })
})

describe('loadTokensFromStorage', () => {
  it('loads tokens from localStorage into the store', () => {
    localStorage.setItem('access_token', 'stored-access')
    localStorage.setItem('refresh_token', 'stored-refresh')
    const store = useAuthStore()
    store.loadTokensFromStorage()
    expect(store.accessToken).toBe('stored-access')
    expect(store.refreshToken).toBe('stored-refresh')
  })

  it('leaves refs null when localStorage is empty', () => {
    const store = useAuthStore()
    store.loadTokensFromStorage()
    expect(store.accessToken).toBeNull()
    expect(store.refreshToken).toBeNull()
  })
})

describe('clearTokensFromStorage', () => {
  it('removes tokens from localStorage', () => {
    localStorage.setItem('access_token', 'tok')
    localStorage.setItem('refresh_token', 'ref')
    const store = useAuthStore()
    store.clearTokensFromStorage()
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })

  it('nulls the store refs', () => {
    const store = useAuthStore()
    store.accessToken = 'tok'
    store.refreshToken = 'ref'
    store.clearTokensFromStorage()
    expect(store.accessToken).toBeNull()
    expect(store.refreshToken).toBeNull()
  })

  it('removes the Authorization header', () => {
    const store = useAuthStore()
    api.defaults.headers.common['Authorization'] = 'Bearer tok'
    store.clearTokensFromStorage()
    expect(api.defaults.headers.common['Authorization']).toBeUndefined()
  })
})

// ─── logout ───────────────────────────────────────────────────────────────────

describe('logout', () => {
  it('clears authentication state after a successful logout API call', async () => {
    api.post.mockResolvedValueOnce({ data: {} })
    const store = useAuthStore()
    store.isAuthenticated = true
    store.user = { id: 1 }

    await store.logout()

    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
  })

  it('still clears state even when the API call fails', async () => {
    api.post.mockRejectedValueOnce(new Error('Network error'))
    const store = useAuthStore()
    store.isAuthenticated = true
    store.user = { id: 1 }

    await store.logout()

    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
  })

  it('skips the API call when not authenticated', async () => {
    const store = useAuthStore()
    store.isAuthenticated = false

    await store.logout()

    expect(api.post).not.toHaveBeenCalled()
    expect(store.isAuthenticated).toBe(false)
  })
})

// ─── handleLoginCallback ─────────────────────────────────────────────────────

describe('handleLoginCallback', () => {
  it('throws when the URL contains no token params', () => {
    const store = useAuthStore()
    // jsdom/happy-dom default search is empty
    expect(() => store.handleLoginCallback()).toThrow('No tokens found in callback URL')
  })

  it('loads tokens from the URL fragment', async () => {
    api.get
      .mockResolvedValueOnce({ data: { id: 42 } })
      .mockResolvedValueOnce({ data: { codec_match_bonus: 5, codec_mismatch_penalty: 10 } })
    api.put.mockResolvedValueOnce({ data: {} })
    window.history.pushState({}, '', '/auth/callback#access_token=access&refresh_token=refresh')
    const store = useAuthStore()

    await store.handleLoginCallback()

    expect(localStorage.getItem('access_token')).toBe('access')
    expect(localStorage.getItem('refresh_token')).toBe('refresh')
    expect(store.isAuthenticated).toBe(true)
    expect(store.user).toEqual({ id: 42 })
  })
})

// ─── fetchAuthStatus ─────────────────────────────────────────────────────────

describe('fetchAuthStatus', () => {
  it('sets authenticated state from API response', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        authenticated: true,
        user: { id: 42 },
        oidc_enabled: true,
        local_auth_enabled: false,
      },
    })
    const store = useAuthStore()

    await store.fetchAuthStatus()

    expect(store.isAuthenticated).toBe(true)
    expect(store.user).toEqual({ id: 42 })
    expect(store.oidcEnabled).toBe(true)
    expect(store.localAuthEnabled).toBe(false)
    expect(store.isLoading).toBe(false)
  })

  it('keeps local auth enabled when older status responses omit the field', async () => {
    api.get.mockResolvedValueOnce({
      data: { authenticated: false, user: null, oidc_enabled: false },
    })
    const store = useAuthStore()

    await store.fetchAuthStatus()

    expect(store.oidcEnabled).toBe(false)
    expect(store.localAuthEnabled).toBe(true)
  })

  it('marks unauthenticated when the API call fails', async () => {
    api.get.mockRejectedValueOnce(new Error('Server error'))
    const store = useAuthStore()
    store.isAuthenticated = true

    await store.fetchAuthStatus()

    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
  })
})
