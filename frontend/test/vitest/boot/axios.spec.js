import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mutable auth store captured by the boot closure — mutate per test.
const mockAuthStore = vi.hoisted(() => ({
  accessToken: null,
  refreshToken: null,
  isAuthenticated: false,
  refreshAccessToken: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('src/stores/auth', () => ({
  useAuthStore: () => mockAuthStore,
}))

vi.mock('src/utils/authStorage', () => ({
  getAccessToken: vi.fn(() => null),
  getServerUrl: vi.fn(() => ''),
}))

vi.mock('src/utils/logger', () => ({
  logger: { debug: vi.fn(), log: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

import bootAxios, { api } from 'src/boot/axios'

const mockRouter = { push: vi.fn() }

// Register the interceptors exactly once (the boot file registers on the
// module-level api instance, so repeated boots would stack handlers).
bootAxios({ app: { config: { globalProperties: {} } }, router: mockRouter })

// The single response interceptor registered by the boot function.
const responseRejected = api.interceptors.response.handlers[0].rejected

// Replace the network layer so retried requests never hit the wire.
const adapter = vi.fn(async (config) => ({
  data: { ok: true },
  status: 200,
  statusText: 'OK',
  headers: {},
  config,
}))
api.defaults.adapter = adapter

function make401(url, config = {}) {
  const requestConfig = { url, headers: {}, ...config }
  return {
    config: requestConfig,
    response: { status: 401, data: { detail: 'unauthorized' } },
    message: 'Request failed with status code 401',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockAuthStore.accessToken = null
  mockAuthStore.refreshToken = null
  mockAuthStore.isAuthenticated = false
  mockAuthStore.refreshAccessToken.mockResolvedValue(undefined)
})

describe('response interceptor: 401 on normal requests', () => {
  it('refreshes the token and retries the original request', async () => {
    mockAuthStore.refreshToken = 'refresh-token'
    mockAuthStore.refreshAccessToken.mockImplementation(async () => {
      mockAuthStore.accessToken = 'new-token'
    })
    const error = make401('/api/media/items')

    const response = await responseRejected(error)

    expect(mockAuthStore.refreshAccessToken).toHaveBeenCalledTimes(1)
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(adapter.mock.calls[0][0].url).toBe('/api/media/items')
    expect(adapter.mock.calls[0][0].headers.Authorization).toBe('Bearer new-token')
    expect(response.data).toEqual({ ok: true })
  })

  it('marks the request as retried so a second 401 cannot loop', async () => {
    mockAuthStore.refreshToken = 'refresh-token'
    mockAuthStore.refreshAccessToken.mockImplementation(async () => {
      mockAuthStore.accessToken = 'new-token'
    })
    const error = make401('/api/media/items')

    await responseRejected(error)
    expect(error.config._retry).toBe(true)

    // Same request 401s again after the retry: no second refresh attempt.
    await expect(responseRejected(error)).rejects.toBe(error)
    expect(mockAuthStore.refreshAccessToken).toHaveBeenCalledTimes(1)
  })
})

describe('response interceptor: 401 on auth endpoints', () => {
  it.each(['/api/auth/logout', '/api/auth/refresh', '/api/auth/login', '/api/auth/status'])(
    'does not attempt a refresh or redirect for %s',
    async (url) => {
      mockAuthStore.refreshToken = 'refresh-token'
      const error = make401(url)

      await expect(responseRejected(error)).rejects.toBe(error)

      expect(mockAuthStore.refreshAccessToken).not.toHaveBeenCalled()
      expect(adapter).not.toHaveBeenCalled()
      expect(mockRouter.push).not.toHaveBeenCalled()
    },
  )
})

describe('response interceptor: 401 on stream endpoints', () => {
  it('does not attempt a JWT refresh for play-token stream requests', async () => {
    mockAuthStore.refreshToken = 'refresh-token'
    const error = make401('/api/stream/abc/master.m3u8')

    await expect(responseRejected(error)).rejects.toBe(error)

    expect(mockAuthStore.refreshAccessToken).not.toHaveBeenCalled()
    expect(mockRouter.push).not.toHaveBeenCalled()
  })
})

describe('response interceptor: 403 responses', () => {
  it('rejects without redirecting to login (only 401 redirects)', async () => {
    const error = {
      config: { url: '/api/admin/users', headers: {} },
      response: { status: 403, data: { detail: 'forbidden' } },
    }

    await expect(responseRejected(error)).rejects.toBe(error)

    expect(mockRouter.push).not.toHaveBeenCalled()
    expect(mockAuthStore.refreshAccessToken).not.toHaveBeenCalled()
    expect(mockAuthStore.logout).not.toHaveBeenCalled()
  })
})

describe('response interceptor: failed refresh', () => {
  it('logs out, redirects to login once, and rejects with the refresh error', async () => {
    mockAuthStore.refreshToken = 'refresh-token'
    const refreshError = new Error('refresh failed')
    mockAuthStore.refreshAccessToken.mockRejectedValue(refreshError)
    const error = make401('/api/media/items')

    await expect(responseRejected(error)).rejects.toBe(refreshError)

    expect(mockAuthStore.logout).toHaveBeenCalledTimes(1)
    expect(mockRouter.push).toHaveBeenCalledTimes(1)
    expect(mockRouter.push).toHaveBeenCalledWith('/auth/login')
    expect(adapter).not.toHaveBeenCalled()
  })

  it('does not retry the refresh when the same request 401s again (no endless loop)', async () => {
    mockAuthStore.refreshToken = 'refresh-token'
    mockAuthStore.refreshAccessToken.mockRejectedValue(new Error('refresh failed'))
    const error = make401('/api/media/items')

    await expect(responseRejected(error)).rejects.toThrow('refresh failed')
    // _retry is now set — a repeated 401 must fall through without refreshing.
    await expect(responseRejected(error)).rejects.toBe(error)

    expect(mockAuthStore.refreshAccessToken).toHaveBeenCalledTimes(1)
  })
})

describe('response interceptor: 401 without a refresh token', () => {
  it('redirects unauthenticated users to login without attempting a refresh call', async () => {
    mockAuthStore.refreshToken = null
    mockAuthStore.isAuthenticated = false
    const error = make401('/api/media/items')

    await expect(responseRejected(error)).rejects.toBe(error)

    expect(mockAuthStore.refreshAccessToken).not.toHaveBeenCalled()
    expect(mockRouter.push).toHaveBeenCalledWith('/auth/login')
  })
})
