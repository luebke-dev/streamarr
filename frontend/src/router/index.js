import { defineRouter } from '#q-app/wrappers'
import {
  createRouter,
  createMemoryHistory,
  createWebHistory,
  createWebHashHistory,
} from 'vue-router'
import routes from './routes'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'

// Install status is checked at most once per app load and cached. We default to
// "installed" so a failing/unreachable status endpoint never traps users on the
// wizard; a fresh (uninstalled) instance flips this to false and routes to
// /install until setup completes.
let installStatusChecked = false
let isInstalled = true

async function ensureInstalled() {
  if (installStatusChecked) return isInstalled
  try {
    const response = await api.get('/api/install/status')
    isInstalled = response.data?.installed !== false
  } catch (error) {
    logger.error('Install status check failed:', error?.response?.status)
    isInstalled = true
  }
  installStatusChecked = true
  return isInstalled
}

/*
 * If not building with SSR mode, you can
 * directly export the Router instantiation;
 *
 * The function below can be async too; either use
 * async/await or return a Promise which resolves
 * with the Router instance.
 */

export default defineRouter(function (/* { store, ssrContext } */) {
  const createHistory = process.env.SERVER
    ? createMemoryHistory
    : process.env.VUE_ROUTER_MODE === 'history'
      ? createWebHistory
      : createWebHashHistory

  const Router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,

    // Leave this as is and make changes in quasar.conf.js instead!
    // quasar.conf.js -> build -> vueRouterMode
    // quasar.conf.js -> build -> publicPath
    history: createHistory(process.env.VUE_ROUTER_BASE),
  })

  // Navigation guards for authentication - ENFORCED VERSION
  Router.beforeEach(async (to, from, next) => {
    try {
      const authStore = useAuthStore()

      // Initialize auth store if not already done
      if (!authStore.initialized) {
        try {
          await authStore.initialize()
        } catch (error) {
          logger.error('Auth initialization failed:', error)
          // If initialization fails, treat as unauthenticated
        }
      }

      // Fresh-instance guard: until the deployment is installed, funnel every
      // route to the install wizard. Once installed, the wizard is redundant so
      // send it to the login page. Skip this gate for authenticated users so a
      // stale/false negative can never lock out a working install.
      if (!authStore.isLoggedIn) {
        const installed = await ensureInstalled()
        if (!installed) {
          if (to.path === '/install') {
            next()
            return
          }
          next('/install')
          return
        }
        if (to.path === '/install') {
          next('/auth/login')
          return
        }
      }

      // Check if route requires authentication
      const requiresAuth = to.matched.some((record) => record.meta.requiresAuth !== false)
      const requiresAdmin = to.matched.some((record) => record.meta.requiresAdmin === true)

      // Allow access to auth routes without authentication
      if (to.path.startsWith('/auth/')) {
        // If already authenticated and trying to access login, redirect to home
        if (authStore.isLoggedIn && to.path === '/auth/login') {
          next('/')
          return
        }
        next()
        return
      }

      // Check authentication for protected routes
      if (requiresAuth) {
        if (!authStore.isLoggedIn) {
          // Store intended destination for redirect after login
          const redirectPath = to.fullPath !== '/' ? to.fullPath : undefined
          next({
            path: '/auth/login',
            query: redirectPath ? { redirect: redirectPath } : {},
          })
          return
        }

        // Check admin access for admin routes
        if (requiresAdmin && !authStore.isAdmin) {
          logger.warn('Access denied: Admin privileges required')
          next('/')
          return
        }
      }

      // Allow navigation
      next()
    } catch (error) {
      logger.error('Router guard error:', error)
      // On error, redirect to login for safety
      next('/auth/login')
    }
  })

  // Handle navigation errors
  Router.onError((error) => {
    logger.error('Router error:', error)
  })

  return Router
})
