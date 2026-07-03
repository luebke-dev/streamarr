import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock auth store — the guard only reads initialized/isLoggedIn/isAdmin and
// calls initialize(); a plain mutable object keeps the test free of pinia.
const mockAuthStore = vi.hoisted(() => ({
  initialized: true,
  isLoggedIn: false,
  isAdmin: false,
  initialize: vi.fn(),
}))

vi.mock('src/stores/auth', () => ({
  useAuthStore: () => mockAuthStore,
}))

vi.mock('src/utils/logger', () => ({
  logger: { debug: vi.fn(), log: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

// Replace the real route components (lazy-loaded .vue layouts/pages) with
// stubs while keeping the real path/meta structure the guard evaluates.
vi.mock('src/router/routes', () => {
  const Stub = { template: '<div />' }
  return {
    default: [
      {
        path: '/auth',
        component: Stub,
        meta: { requiresAuth: false },
        children: [
          { path: 'login', component: Stub, meta: { requiresAuth: false } },
          { path: 'forgot-password', component: Stub, meta: { requiresAuth: false } },
        ],
      },
      {
        path: '/',
        component: Stub,
        meta: { requiresAuth: true },
        children: [
          { path: '', component: Stub, meta: { requiresAuth: true, isHome: true } },
          { path: 'favorites', component: Stub, meta: { requiresAuth: true } },
        ],
      },
      {
        path: '/admin',
        component: Stub,
        meta: { requiresAuth: true, requiresAdmin: true },
        children: [{ path: '', component: Stub }],
      },
    ],
  }
})

// The default export is the (identity-wrapped) router factory from defineRouter.
import createAppRouter from 'src/router/index.js'

function buildRouter() {
  // Force createMemoryHistory inside the factory so no browser history is touched.
  process.env.SERVER = 'true'
  return createAppRouter()
}

beforeEach(() => {
  vi.clearAllMocks()
  mockAuthStore.initialized = true
  mockAuthStore.isLoggedIn = false
  mockAuthStore.isAdmin = false
  mockAuthStore.initialize.mockResolvedValue(undefined)
})

describe('router navigation guard', () => {
  it('redirects unauthenticated users on requiresAuth routes to /auth/login with redirect query', async () => {
    const router = buildRouter()

    await router.push('/favorites')

    expect(router.currentRoute.value.path).toBe('/auth/login')
    expect(router.currentRoute.value.query.redirect).toBe('/favorites')
  })

  it('omits the redirect query when the intended destination is the home page', async () => {
    const router = buildRouter()

    await router.push('/')

    expect(router.currentRoute.value.path).toBe('/auth/login')
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('lets authenticated users through on requiresAuth routes', async () => {
    mockAuthStore.isLoggedIn = true
    const router = buildRouter()

    await router.push('/favorites')

    expect(router.currentRoute.value.path).toBe('/favorites')
  })

  it('blocks authenticated non-admin users from requiresAdmin routes', async () => {
    mockAuthStore.isLoggedIn = true
    mockAuthStore.isAdmin = false
    const router = buildRouter()

    await router.push('/admin')

    expect(router.currentRoute.value.path).toBe('/')
  })

  it('lets admins through on requiresAdmin routes', async () => {
    mockAuthStore.isLoggedIn = true
    mockAuthStore.isAdmin = true
    const router = buildRouter()

    await router.push('/admin')

    expect(router.currentRoute.value.path).toBe('/admin')
  })

  it('allows public routes without authentication', async () => {
    const router = buildRouter()

    await router.push('/auth/forgot-password')

    expect(router.currentRoute.value.path).toBe('/auth/forgot-password')
  })

  it('redirects already-authenticated users away from the login page', async () => {
    mockAuthStore.isLoggedIn = true
    const router = buildRouter()

    await router.push('/auth/login')

    expect(router.currentRoute.value.path).toBe('/')
  })

  it('initializes the auth store before evaluating a navigation', async () => {
    mockAuthStore.initialized = false
    mockAuthStore.initialize.mockImplementation(async () => {
      mockAuthStore.isLoggedIn = true
    })
    const router = buildRouter()

    await router.push('/favorites')

    expect(mockAuthStore.initialize).toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/favorites')
  })

  it('treats users as unauthenticated when auth initialization fails', async () => {
    mockAuthStore.initialized = false
    mockAuthStore.initialize.mockRejectedValue(new Error('boom'))
    const router = buildRouter()

    await router.push('/favorites')

    expect(router.currentRoute.value.path).toBe('/auth/login')
  })
})
