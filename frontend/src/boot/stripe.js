/**
 * Stripe.js boot — lazy loader.
 *
 * We intentionally do NOT load Stripe.js at app startup: it's ~50 KB of
 * third-party JS that only the membership flow needs, and the publishable
 * key has to come from the backend so on-prem deployments can ship without
 * any Stripe dependency at all.
 *
 * Components that need Stripe call ``await getStripe()`` which:
 *   1. Fetches ``/api/subscriptions/stripe-config`` (cached after first call)
 *   2. Returns ``null`` if payments are disabled / not configured
 *   3. Otherwise lazy-imports ``@stripe/stripe-js`` and returns the
 *      initialised Stripe instance (also cached)
 */

import { defineBoot } from '#q-app/wrappers'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'

let _configPromise = null
let _stripePromise = null

/**
 * @returns {Promise<{ publishable_key: string | null }>}
 */
function fetchStripeConfig() {
  if (_configPromise) return _configPromise
  _configPromise = api
    .get('/api/subscriptions/stripe-config')
    .then((r) => r.data)
    .catch((err) => {
      // Reset so a later retry can succeed (e.g. backend was down at boot).
      _configPromise = null
      throw err
    })
  return _configPromise
}

/**
 * Lazily initialise Stripe.js.
 *
 * @returns {Promise<import('@stripe/stripe-js').Stripe | null>}
 *   The Stripe instance, or ``null`` when the backend reports no
 *   publishable key (payments disabled).
 */
export async function getStripe() {
  if (_stripePromise) return _stripePromise

  _stripePromise = (async () => {
    let config
    try {
      config = await fetchStripeConfig()
    } catch (err) {
      logger.error('Failed to load Stripe config', err)
      _stripePromise = null
      return null
    }

    if (!config?.publishable_key) {
      // Payments not configured — let callers fall back to an empty UI.
      return null
    }

    try {
      const { loadStripe } = await import('@stripe/stripe-js')
      return await loadStripe(config.publishable_key)
    } catch (err) {
      logger.error('Failed to load Stripe.js', err)
      _stripePromise = null
      return null
    }
  })()

  return _stripePromise
}

/**
 * Reset cached Stripe + config (useful after switching backend URL on the
 * login page, otherwise we'd keep using the old publishable key).
 */
export function resetStripe() {
  _configPromise = null
  _stripePromise = null
}

export default defineBoot(({ app }) => {
  // Expose the helper on Options-API instances for parity with $api.
  app.config.globalProperties.$getStripe = getStripe
})
